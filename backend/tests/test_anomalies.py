import json
import pytest
from fastapi.testclient import TestClient

from app.core.security import REVOKED_JTIS, get_db_dependency
from app.db.connection import get_connection
from app.db.seed import DEV_DEFAULT_PASSWORD, seed_database
from app.main import app
from app.services.anomaly_service import RULE_SQL_FILES, SQL_DIR, run_anomaly_scan


@pytest.fixture()
def anomaly_env(tmp_path):
    db_file = tmp_path / "anom_test.db"
    seed_database(db_path=db_file, reset=True)
    REVOKED_JTIS.clear()

    def _override_db():
        conn = get_connection(db_file, readonly=False)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db_dependency] = _override_db
    with TestClient(app) as client:
        yield client, db_file
    app.dependency_overrides.clear()


def _login(client: TestClient, username: str):
    resp = client.post("/api/auth/login", json={"username": username, "password": DEV_DEFAULT_PASSWORD})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_all_8_sql_files_exist():
    assert len(RULE_SQL_FILES) == 8
    for _, _, filename in RULE_SQL_FILES:
        path = SQL_DIR / filename
        assert path.exists(), f"Missing SQL rule file: {filename}"


def test_detects_all_scenarios_s1_to_s7_and_r3_idempotently(anomaly_env):
    _, db_file = anomaly_env
    conn = get_connection(db_file)
    try:
        first_scan = run_anomaly_scan(conn, period=None)
        assert first_scan["inserted"] > 0
        for code in ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]:
            assert first_scan["by_rule"][code] >= 1, f"Rule {code} did not trigger on seeded data!"

        # Idempotency: second scan must insert 0 duplicates
        second_scan = run_anomaly_scan(conn, period=None)
        assert second_scan["inserted"] == 0
        assert second_scan["updated"] == first_scan["total_detected"]

        rows = [dict(r) for r in conn.execute("SELECT * FROM v_anomalies").fetchall()]

        # S1 -> R1 NV007 Oct 2026 (8 late days -> medium)
        s1 = [r for r in rows if r["rule_code"] == "R1" and r["employee_id"] == "NV007" and r["period"] == "2026-10"]
        assert len(s1) == 1
        assert s1[0]["severity"] == "medium"
        assert json.loads(s1[0]["evidence"])["late_days"] == 8

        # S2 -> R2 NV015 Sep 2026 (4 missing punch days -> medium)
        s2 = [r for r in rows if r["rule_code"] == "R2" and r["employee_id"] == "NV015" and r["period"] == "2026-09"]
        assert len(s2) == 1
        assert s2[0]["severity"] == "medium"
        assert json.loads(s2[0]["evidence"])["missing_days"] == 4

        # Bonus R3 -> NV060 Oct 2026 (6 low hour days -> low)
        r3 = [r for r in rows if r["rule_code"] == "R3" and r["employee_id"] == "NV060" and r["period"] == "2026-10"]
        assert len(r3) == 1
        assert r3[0]["severity"] == "low"

        # S4 -> R4 NV031 Sep 2026 (3 leaves around 2026-09-02 -> medium)
        s4 = [r for r in rows if r["rule_code"] == "R4" and r["employee_id"] == "NV031"]
        assert len(s4) == 1
        assert s4[0]["severity"] == "medium"

        # S5 -> R5 DEPT_SALES 2026-10-16 (6/16 = 37.5% -> medium, scope_type='department', employee_id=None)
        s5 = [r for r in rows if r["rule_code"] == "R5" and r["department_id"] == "DEPT_SALES" and r["period"] == "2026-10"]
        assert len(s5) == 1
        assert s5[0]["scope_type"] == "department"
        assert s5[0]["employee_id"] is None
        assert s5[0]["severity"] == "medium"
        assert json.loads(s5[0]["evidence"])["leave_count"] == 6

        # S3 -> R6 NV023 Nov 2026 (10 identical punches -> high)
        s3 = [r for r in rows if r["rule_code"] == "R6" and r["employee_id"] == "NV023" and r["period"] == "2026-11"]
        assert len(s3) == 1
        assert s3[0]["severity"] == "high"
        assert json.loads(s3[0]["evidence"])["identical_days"] == 10

        # S6 -> R7 NV045 Oct 2026 (3 Saturdays -> low)
        s6 = [r for r in rows if r["rule_code"] == "R7" and r["employee_id"] == "NV045" and r["period"] == "2026-10"]
        assert len(s6) == 1
        assert s6[0]["severity"] == "low"
        assert json.loads(s6[0]["evidence"])["weekend_holiday_days"] == 3

        # S7 -> R8 NV052 (17 days approved annual leave > 12 -> medium)
        s7 = [r for r in rows if r["rule_code"] == "R8" and r["employee_id"] == "NV052"]
        assert len(s7) == 1
        assert s7[0]["severity"] == "medium"
        assert json.loads(s7[0]["evidence"])["approved_annual_days"] == 17.0

        # Verify neutral wording across ALL explanations (no accusatory labels)
        forbidden = ["gian lận", "lười", "vi phạm kỷ luật"]
        for r in rows:
            lower_exp = r["explanation"].lower()
            for word in forbidden:
                assert word not in lower_exp, f"Forbidden accusatory word '{word}' found in explanation!"
    finally:
        conn.close()


def test_severity_boundaries_and_r7_overtime_exclusion(anomaly_env):
    _, db_file = anomaly_env
    conn = get_connection(db_file)
    try:
        # Push NV007 Oct 2026 from 8 late days to 10 late days -> R1 severity MUST upgrade from medium to high!
        conn.execute(
            """
            UPDATE attendance
            SET check_in = work_date || ' 08:55:00'
            WHERE employee_id = 'NV007' AND work_date IN ('2026-10-01', '2026-10-06')
            """
        )
        # Add an approved overtime_request for NV045 on 2026-10-03 -> weekend count drops from 3 to 2
        conn.execute(
            """
            INSERT INTO overtime_requests (employee_id, work_date, status, approved_by)
            VALUES ('NV045', '2026-10-03', 'approved', 'NV002')
            """
        )
        conn.commit()

        run_anomaly_scan(conn, period="2026-10")
        r1 = conn.execute(
            "SELECT severity, evidence FROM v_anomalies WHERE rule_code = 'R1' AND employee_id = 'NV007' AND period = '2026-10'"
        ).fetchone()
        assert r1["severity"] == "high"
        assert json.loads(r1["evidence"])["late_days"] == 10

        r7 = conn.execute(
            "SELECT evidence FROM v_anomalies WHERE rule_code = 'R7' AND employee_id = 'NV045' AND period = '2026-10'"
        ).fetchone()
        assert json.loads(r7["evidence"])["weekend_holiday_days"] == 2
    finally:
        conn.close()


def test_anomaly_api_rbac_and_review_workflow(anomaly_env):
    client, _ = anomaly_env
    emp_headers = _login(client, "nv007@company.vn")
    mgr_sales_headers = _login(client, "manager.sales@company.vn")
    mgr_tech_headers = _login(client, "manager.tech@company.vn")
    hr_headers = _login(client, "hr@company.vn")

    # Employee cannot trigger scan
    assert client.post("/api/anomalies/scan", headers=emp_headers).status_code == 403

    # HR triggers scan
    scan_resp = client.post("/api/anomalies/scan", headers=hr_headers)
    assert scan_resp.status_code == 200
    assert scan_resp.json()["total_detected"] >= 8

    # Employee sees ONLY personal NV007 anomalies (no R5 department cluster leaking colleagues)
    emp_list = client.get("/api/anomalies", headers=emp_headers)
    assert emp_list.status_code == 200
    emp_items = emp_list.json()["items"]
    assert len(emp_items) >= 1
    assert all(i["scope_type"] == "employee" and i["employee_id"] == "NV007" for i in emp_items)
    nv007_anom_id = emp_items[0]["anomaly_id"]

    # Employee cannot review anomalies (403)
    assert client.post(
        f"/api/anomalies/{nv007_anom_id}/review",
        headers=emp_headers,
        json={"review_status": "dismissed"},
    ).status_code == 403

    # Manager of Tech (other dept) cannot view or review NV007's anomaly (403)
    assert client.get(f"/api/anomalies/{nv007_anom_id}", headers=mgr_tech_headers).status_code == 403
    assert client.post(
        f"/api/anomalies/{nv007_anom_id}/review",
        headers=mgr_tech_headers,
        json={"review_status": "confirmed"},
    ).status_code == 403

    # Manager of Sales sees DEPT_SALES anomalies including R5 department cluster and CAN review NV007
    mgr_list = client.get("/api/anomalies?period=2026-10", headers=mgr_sales_headers)
    assert mgr_list.status_code == 200
    assert any(i["rule_code"] == "R5" and i["scope_type"] == "department" for i in mgr_list.json()["items"])

    rev_resp = client.post(
        f"/api/anomalies/{nv007_anom_id}/review",
        headers=mgr_sales_headers,
        json={"review_status": "confirmed", "review_note": "Đã trao đổi với nhân viên"},
    )
    assert rev_resp.status_code == 200
    assert rev_resp.json()["anomaly"]["review_status"] == "confirmed"
    assert rev_resp.json()["anomaly"]["reviewed_by"] == "NV001"

    # Re-scanning MUST preserve human 'confirmed' review status!
    client.post("/api/anomalies/scan?period=2026-10", headers=hr_headers)
    after_rescan = client.get(f"/api/anomalies/{nv007_anom_id}", headers=mgr_sales_headers).json()
    assert after_rescan["review_status"] == "confirmed"
