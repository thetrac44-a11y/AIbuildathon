from __future__ import annotations

import io
from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from app.core.config import Settings
from app.core.security import get_db_dependency, load_authenticated_user
from app.db.connection import get_connection
from app.db.seed import seed_database
from app.main import app
from app.services.import_service import has_formula_injection
from app.services.sql_guard import SQLGuardError, execute_guarded_sql, validate_readonly_sql


@pytest.fixture()
def sec_env(tmp_path: Path):
    db_path = tmp_path / "sec_review.db"
    seed_database(db_path=db_path, reset=True)

    def _override_db():
        conn = get_connection(db_path=db_path, readonly=False)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db_dependency] = _override_db
    client = TestClient(app)
    yield client, db_path
    app.dependency_overrides.clear()


def _login(client: TestClient, username: str, password: str = "Demo@123") -> dict[str, str]:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_sec01_sql_guard_blocks_advanced_bypass_vectors(sec_env):
    """Verify quoted/bracketed identifiers, comma-joins, raw base tables, PII columns, and subquery LIMIT bypasses are blocked."""
    _, db_path = sec_env
    conn = get_connection(db_path=db_path, readonly=True)
    uid = conn.execute("SELECT user_id FROM users WHERE employee_id = 'NV007'").fetchone()["user_id"]
    emp_user = load_authenticated_user(conn, uid)
    conn.close()
    assert emp_user is not None

    bypass_payloads = [
        'SELECT employee_id, email, phone FROM "employees"',
        "SELECT * FROM `employees`",
        "SELECT * FROM [attendance]",
        "SELECT * FROM v_employees, employees",
        "SELECT * FROM v_employees e, attendance a",
        "SELECT * FROM departments",
        "SELECT * FROM leave_requests",
        "SELECT * FROM anomalies",
        "SELECT * FROM holidays",
        "SELECT * FROM overtime_requests",
        "SELECT employee_id, email FROM v_employees",
        "SELECT employee_id, phone FROM v_employees",
        "SELECT * FROM temp.v_employees",
    ]
    for bad_sql in bypass_payloads:
        with pytest.raises(SQLGuardError):
            execute_guarded_sql(db_path, emp_user, bad_sql)

    # Outer LIMIT must still be appended even when a subquery contains LIMIT
    subquery_sql = (
        "SELECT employee_id, work_date FROM v_attendance_daily "
        "WHERE employee_id IN (SELECT employee_id FROM v_employees LIMIT 1)"
    )
    validated = validate_readonly_sql(subquery_sql, max_rows=200)
    assert validated.endswith("LIMIT 200")


def test_sec02_formula_injection_blocks_leading_minus_and_control_chars():
    assert has_formula_injection("=CMD|' /C calc'!A0") is True
    assert has_formula_injection("+2+3+cmd|' /C calc'!A0") is True
    assert has_formula_injection("@SUM(1+1)*cmd|' /C calc'!A0") is True
    assert has_formula_injection("-1+1+cmd|' /C calc'!A0") is True
    assert has_formula_injection("\t=1+1") is True
    assert has_formula_injection("\r\n-cmd|' /C calc'!A0") is True
    # Safe regular values & plain numeric strings are not misclassified as formula injection
    assert has_formula_injection("Nguyễn Văn An") is False
    assert has_formula_injection("2026-10-15") is False
    assert has_formula_injection("-5") is False


def test_sec03_production_runtime_rejects_default_or_short_jwt_secret():
    with pytest.raises(RuntimeError):
        Settings(app_env="production", jwt_secret_key="dev-only-jwt-secret-key-change-in-production-32bytes").validate_runtime_security()
    with pytest.raises(RuntimeError):
        Settings(app_env="production", jwt_secret_key="short-secret").validate_runtime_security()
    # Strong production key succeeds
    Settings(app_env="production", jwt_secret_key="a-very-strong-random-production-secret-key-64-chars-long").validate_runtime_security()


def test_sec04_manager_anomaly_scan_does_not_leak_other_departments(sec_env):
    client, db_path = sec_env
    hr_headers = _login(client, "hr@company.vn")
    mgr_sales_headers = _login(client, "manager.sales@company.vn")

    hr_scan = client.post("/api/anomalies/scan", headers=hr_headers)
    assert hr_scan.status_code == 200
    hr_total = hr_scan.json()["total_detected"]

    mgr_scan = client.post("/api/anomalies/scan", headers=mgr_sales_headers)
    assert mgr_scan.status_code == 200
    mgr_data = mgr_scan.json()
    # Manager Sales must see strictly fewer anomalies than company-wide HR scan (zero cross-dept metadata leak)
    assert mgr_data["total_detected"] < hr_total

    conn = get_connection(db_path=db_path, readonly=True)
    sales_count = conn.execute("SELECT COUNT(*) FROM v_anomalies WHERE department_id = 'DEPT_SALES'").fetchone()[0]
    conn.close()
    assert mgr_data["total_detected"] == sales_count
    # Non-Sales R6 (NV023) & R8 (NV052) must not leak into Sales Manager's scan summary
    assert mgr_data["by_rule"]["R6"] == 0
    assert mgr_data["by_rule"]["R8"] == 0


def test_sec05_sec07_security_headers_and_strict_scope_isolation(sec_env):
    client, _ = sec_env
    emp_headers = _login(client, "nv007@company.vn")
    hr_headers = _login(client, "hr@company.vn")

    # Security headers present on API response
    dash = client.get("/api/dashboard/summary?period=2026-10", headers=emp_headers)
    assert dash.status_code == 200
    assert dash.headers.get("X-Content-Type-Options") == "nosniff"
    assert dash.headers.get("X-Frame-Options") == "DENY"
    assert dash.headers.get("Cache-Control") == "no-store"

    # Employee dashboard top_alerts must NEVER contain department-scoped R5 alerts
    for alert in dash.json()["top_alerts"]:
        assert alert["scope_type"] == "employee"
        assert alert["employee_id"] == "NV007"

    # Role escalation attempt via self-profile PATCH is rejected (422 extra=forbid)
    esc = client.patch("/api/profile", headers=emp_headers, json={"phone": "0909999999", "role": "hr"})
    assert esc.status_code == 422

    # Chat history isolation between HR and Employee
    client.post("/api/assistant/ask", headers=hr_headers, json={"question": "Phòng nào có tỷ lệ đi muộn cao nhất tháng 10/2026?"})
    emp_hist = client.get("/api/assistant/history", headers=emp_headers)
    assert emp_hist.status_code == 200
    assert all("Phòng nào" not in item["question"] for item in emp_hist.json()["items"])


def test_sec08_import_batch_ownership_enforced(sec_env):
    client, _ = sec_env
    hr1 = _login(client, "hr@company.vn")
    hr2 = _login(client, "hr2@company.vn")

    csv_content = "employee_id,work_date,check_in,check_out,status\nNV007,2026-12-01,2026-12-01 08:25:00,2026-12-01 17:35:00,present\n"
    prev = client.post(
        "/api/imports/preview",
        headers=hr1,
        data={"data_type": "attendance"},
        files={"file": ("test.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")},
    )
    assert prev.status_code == 200
    batch_id = prev.json()["batch_id"]

    # HR2 cannot download errors or confirm HR1's staged batch
    err_dl = client.get(f"/api/imports/errors/{batch_id}", headers=hr2)
    assert err_dl.status_code == 403
    conf = client.post(f"/api/imports/confirm/{batch_id}", headers=hr2, json={"duplicate_policy": "skip"})
    assert conf.status_code == 403


def test_sec09_manager_ai_no_employee_existence_oracle(sec_env):
    client, _ = sec_env
    mgr_sales = _login(client, "manager.sales@company.vn")

    # Asking about an existing outside-department employee (NV052) vs non-existent (NV999) both return uniform blocked phrasing
    r1 = client.post("/api/assistant/ask", headers=mgr_sales, json={"question": "NV052 còn bao nhiêu ngày phép?"})
    r2 = client.post("/api/assistant/ask", headers=mgr_sales, json={"question": "NV999 còn bao nhiêu ngày phép?"})
    assert r1.status_code == 200 and r1.json()["status"] == "blocked"
    assert r2.status_code == 200 and r2.json()["status"] == "blocked"
    assert "không thuộc phòng" in r1.json()["answer"]
    assert "không thuộc phòng" in r2.json()["answer"]
