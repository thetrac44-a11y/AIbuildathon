from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from app.core.security import (
    REVOKED_JTIS,
    get_db_dependency,
    load_authenticated_user,
    resolve_ai_effective_scope,
)
from app.db.connection import get_connection
from app.db.seed import DEV_DEFAULT_PASSWORD, seed_database
from app.main import app
from app.services.anomaly_service import run_anomaly_scan
from app.services.sql_guard import SQLGuardError, execute_guarded_sql, validate_readonly_sql


@pytest.fixture()
def phase1_env(tmp_path: Path):
    db_file = tmp_path / "ai_phase1.db"
    seed_database(db_path=db_file, reset=True)
    conn = get_connection(db_file, readonly=False)
    run_anomaly_scan(conn, period=None)
    conn.close()
    REVOKED_JTIS.clear()

    def _override_db():
        c = get_connection(db_file, readonly=False)
        try:
            yield c
        finally:
            c.close()

    app.dependency_overrides[get_db_dependency] = _override_db
    with TestClient(app) as client:
        yield client, db_file
    app.dependency_overrides.clear()


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/auth/login", json={"username": username, "password": DEV_DEFAULT_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# =============================================================================
# 1. SQL GUARD v2 (AST PARSER, COLUMN ALLOWLIST, PG SYSTEM FUNCTIONS, SETTINGS)
# =============================================================================

def test_sql_guard_v2_blocks_pg_functions_disallowed_columns_and_locking():
    blocked_queries = [
        # PostgreSQL / SQLite system & DoS functions
        "SELECT pg_sleep(5) FROM v_employees",
        "SELECT pg_read_file('/etc/passwd') FROM v_employees",
        "SELECT current_setting('is_superuser') FROM v_employees",
        "SELECT set_config('search_path', 'public', false) FROM v_employees",
        "SELECT version() FROM v_employees",
        "SELECT dblink('host=evil', 'SELECT 1') FROM v_employees",
        "SELECT lo_import('/etc/passwd') FROM v_employees",
        "SELECT randomblob(100000000) FROM v_employees",
        "SELECT current_user FROM v_employees",
        "SELECT session_user FROM v_employees",
        # Disallowed / unknown / cross-view columns (ALLOWED_VIEW_COLUMNS enforcement)
        "SELECT secret_col FROM v_employees",
        "SELECT e.email FROM v_employees e",
        "SELECT e.late_minutes FROM v_employees e",
        "SELECT a.annual_leave_balance FROM v_attendance_daily a",
        "SELECT nonexistent_field FROM v_anomalies",
        # Locking / INTO / no-view queries
        "SELECT employee_id FROM v_employees FOR UPDATE",
        "SELECT employee_id INTO temp_copy FROM v_employees",
        "SELECT 1 + 1",
    ]
    for q in blocked_queries:
        with pytest.raises(SQLGuardError, match="."):
            validate_readonly_sql(q)

    # Valid analytical CTE + JOIN queries pass AST validation cleanly
    valid_queries = [
        "SELECT employee_id, full_name FROM v_employees WHERE role = 'employee' ORDER BY employee_id",
        (
            "WITH late_counts AS ("
            "  SELECT employee_id, COUNT(*) AS late_cnt FROM v_attendance_daily WHERE is_late = 1 GROUP BY employee_id"
            ") "
            "SELECT e.employee_id, e.full_name, COALESCE(l.late_cnt, 0) AS total_late "
            "FROM v_employees e LEFT JOIN late_counts l ON l.employee_id = e.employee_id "
            "ORDER BY total_late DESC"
        ),
        (
            "SELECT department_name, COUNT(*) AS cnt, ROUND(AVG(late_minutes), 1) AS avg_m "
            "FROM v_attendance_daily WHERE period = '2026-10' AND is_late = 1 GROUP BY department_name"
        ),
        (
            "SELECT employee_id, SUM(CASE WHEN is_late = 1 THEN 1 ELSE 0 END) AS late_cnt "
            "FROM v_attendance_daily WHERE (period = '2026-09' OR period = '2026-10') AND status != 'absent' "
            "GROUP BY employee_id HAVING COUNT(*) >= 1"
        ),
    ]
    for q in valid_queries:
        validated = validate_readonly_sql(q, max_rows=200)
        assert validated.endswith("LIMIT 200")


def test_sql_guard_v2_respects_system_settings_and_effective_scope_narrowing(phase1_env):
    client, db_file = phase1_env
    admin = _login(client, "admin@company.vn")
    hr = _login(client, "hr@company.vn")

    # Update ai.sql_max_rows to 15 via Admin System Config
    upd = client.patch(
        "/api/system/config",
        headers=admin,
        json={"settings": [{"setting_key": "ai.sql_max_rows", "setting_value": "15"}]},
    )
    assert upd.status_code == 200

    conn = get_connection(db_file, readonly=True)
    hr_user = load_authenticated_user(conn, "USR002")
    admin_user = load_authenticated_user(conn, "USR080")
    conn.close()
    assert hr_user is not None and admin_user is not None

    rows, validated_sql, _ = execute_guarded_sql(db_file, hr_user, "SELECT employee_id FROM v_employees")
    assert "LIMIT 15" in validated_sql
    assert len(rows) == 15

    # Narrow HR AI permission from ai.ask.all -> ai.ask.department (HR belongs to DEPT_HR: 16 employees)
    roles = client.get("/api/rbac/roles", headers=admin).json()["items"]
    hr_orig = next(r["permissions"] for r in roles if r["role_code"] == "hr")
    narrowed = [p for p in hr_orig if p != "ai.ask.all"] + ["ai.ask.department"]
    assert client.patch("/api/rbac/roles/hr/permissions", headers=admin, json={"permissions": narrowed}).status_code == 200

    conn = get_connection(db_file, readonly=True)
    hr_narrowed = load_authenticated_user(conn, "USR002")
    conn.close()
    assert hr_narrowed is not None
    assert resolve_ai_effective_scope(hr_narrowed) == "department"

    # SQL Guard TEMP views must immediately scope narrowed HR to DEPT_HR (16 rows, not 80!)
    cnt_rows, _, _ = execute_guarded_sql(db_file, hr_narrowed, "SELECT COUNT(*) AS cnt FROM v_employees", max_rows=200)
    assert cnt_rows[0]["cnt"] == 16

    # AI Assistant endpoint must also block narrowed HR from querying DEPT_SALES
    blocked_sales = client.post(
        "/api/assistant/ask",
        headers=hr,
        json={"question": "Tổng hợp chấm công phòng Kinh doanh tháng 10/2026"},
    ).json()
    assert blocked_sales["status"] == "blocked"
    assert blocked_sales["trace"]["tool_name"] == "rbac_guard"

    # Even if Admin accidentally assigns ai.ask.all to admin role -> Admin MUST remain blocked!
    admin_orig = next(r["permissions"] for r in roles if r["role_code"] == "admin")
    assert (
        client.patch(
            "/api/rbac/roles/admin/permissions",
            headers=admin,
            json={"permissions": sorted(set([*admin_orig, "ai.ask.all"]))},
        ).status_code
        == 200
    )
    conn = get_connection(db_file, readonly=True)
    admin_misconfigured = load_authenticated_user(conn, "USR080")
    conn.close()
    assert admin_misconfigured is not None
    assert resolve_ai_effective_scope(admin_misconfigured) == "none"
    with pytest.raises(SQLGuardError):
        execute_guarded_sql(db_file, admin_misconfigured, "SELECT COUNT(*) AS cnt FROM v_employees")
    admin_ask = client.post("/api/assistant/ask", headers=admin, json={"question": "Phòng nào đi muộn cao nhất?"}).json()
    assert admin_ask["status"] == "blocked"
    assert admin_ask["trace"]["tool_name"] == "rbac_guard"


# =============================================================================
# 2. PHASE 1 SQL INTELLIGENCE TEST CASES (FROM AI_TEST_CASES.md)
# =============================================================================

def test_phase1_employee_cases_tc01_to_tc10(phase1_env):
    client, _ = phase1_env
    emp = _login(client, "nv007@company.vn")

    # TC-01: Late count AND exact 8 dates in 2026-10
    tc01 = client.post(
        "/api/assistant/ask",
        headers=emp,
        json={"question": "Tháng 10/2026 tôi đi muộn bao nhiêu lần và cụ thể vào những ngày nào?"},
    ).json()
    assert tc01["status"] == "success"
    assert tc01["trace"]["tool_name"] == "get_employee_attendance_detail"
    assert tc01["trace"]["row_count"] == 8
    for expected_date in ("2026-10-02", "2026-10-15", "2026-10-28"):
        assert expected_date in tc01["answer"]

    # TC-03: Leave balance AND pending leave request combined
    tc03 = client.post(
        "/api/assistant/ask",
        headers=emp,
        json={"question": "Tôi còn bao nhiêu ngày phép năm và có đơn nghỉ phép nào đang chờ duyệt không?"},
    ).json()
    assert tc03["status"] == "success"
    assert "12" in tc03["answer"]
    assert "2026-11-18" in tc03["answer"]

    # TC-04: Zero late days in 2026-07 -> status=success (NOT insufficient_data!)
    tc04 = client.post(
        "/api/assistant/ask",
        headers=emp,
        json={"question": "Tháng 07/2026 tôi đi muộn mấy lần?"},
    ).json()
    assert tc04["status"] == "success"
    assert "0 lần đi muộn" in tc04["answer"]
    assert "23 ngày đi làm" in tc04["answer"]

    # TC-05: Top 3 personal late days -> NOT false-positive blocked!
    tc05 = client.post(
        "/api/assistant/ask",
        headers=emp,
        json={"question": "Top 3 ngày tôi đi muộn nhiều phút nhất trong tháng 10/2026?"},
    ).json()
    assert tc05["status"] == "success"
    assert tc05["trace"]["row_count"] == 3
    assert "2026-10-15" in tc05["answer"] and "40 phút" in tc05["answer"]
    assert "2026-10-28" in tc05["answer"] and "35 phút" in tc05["answer"]
    assert "2026-10-08" in tc05["answer"] and "32 phút" in tc05["answer"]

    # TC-06: Personal anomalies only (no department R5 leak!)
    tc06 = client.post("/api/assistant/ask", headers=emp, json={"question": "Tôi có cảnh báo bất thường nào không?"}).json()
    assert tc06["status"] == "success"
    assert "R1" in tc06["answer"]
    assert "R5" not in tc06["answer"]

    # TC-09: Self-service password change help -> NOT false-positive blocked as injection!
    tc09 = client.post(
        "/api/assistant/ask",
        headers=emp,
        json={"question": "Làm sao để tôi đổi mật khẩu tài khoản của mình?"},
    ).json()
    assert tc09["status"] == "success"
    assert "/profile" in tc09["answer"]

    # TC-10: Missing historical period -> honest insufficient_data with available period hint
    tc10 = client.post(
        "/api/assistant/ask",
        headers=emp,
        json={"question": "Cho tôi xem tổng hợp chấm công của tôi tháng 01/2025."},
    ).json()
    assert tc10["status"] == "insufficient_data"
    assert "2025-01" in tc10["answer"]


def test_phase1_manager_cases_tc11_to_tc15(phase1_env):
    client, _ = phase1_env
    mgr = _login(client, "manager.sales@company.vn")

    # TC-11: Sales late count & top late
    tc11 = client.post(
        "/api/assistant/ask",
        headers=mgr,
        json={"question": "Tháng 10/2026 phòng tôi có bao nhiêu người đi muộn và ai đi muộn nhiều nhất?"},
    ).json()
    assert tc11["status"] == "success"
    assert "NV007" in tc11["answer"]

    # TC-12: Detailed pending leave requests in DEPT_SALES (NV007 + NV014)
    tc12 = client.post(
        "/api/assistant/ask",
        headers=mgr,
        json={"question": "Phòng tôi hiện có những đơn nghỉ phép nào đang chờ duyệt?"},
    ).json()
    assert tc12["status"] == "success"
    assert tc12["trace"]["tool_name"] == "list_leave_requests_detail"
    assert "NV007" in tc12["answer"]
    assert "NV014" in tc12["answer"]

    # TC-13: Compare two periods (2026-09 vs 2026-10) in DEPT_SALES
    tc13 = client.post(
        "/api/assistant/ask",
        headers=mgr,
        json={"question": "So sánh tình hình đi muộn của phòng tôi giữa tháng 09/2026 và tháng 10/2026."},
    ).json()
    assert tc13["status"] == "success"
    assert tc13["trace"]["tool_name"] == "compare_periods"
    assert tc13["trace"]["row_count"] == 2
    assert "2026-09" in tc13["answer"] and "2026-10" in tc13["answer"]

    # TC-14: Resolve employee full name in DEPT_SALES (Trần Minh Đức -> NV015 R2)
    tc14 = client.post(
        "/api/assistant/ask",
        headers=mgr,
        json={"question": "Nhân viên Trần Minh Đức trong phòng tôi có cảnh báo bất thường nào không?"},
    ).json()
    assert tc14["status"] == "success"
    assert "NV015" in tc14["answer"] and "R2" in tc14["answer"]
    # Must NOT leak other Sales anomalies like NV007 R1
    assert "NV007" not in tc14["answer"]

    # Cross-department name lookup as Manager Sales MUST NOT leak Tech employee NV023!
    cross_name = client.post(
        "/api/assistant/ask",
        headers=mgr,
        json={"question": "Nhân viên Lê Hoàng Nam có cảnh báo bất thường nào không?"},
    ).json()
    assert "NV023" not in cross_name["answer"]

    # TC-15: Manager asking about OWN leave balance -> ONLY NV001 (1 row, NOT 16!)
    tc15 = client.post(
        "/api/assistant/ask",
        headers=mgr,
        json={"question": "Bản thân tôi còn bao nhiêu ngày phép năm?"},
    ).json()
    assert tc15["status"] == "success"
    assert tc15["trace"]["row_count"] == 1
    assert "NV001" in tc15["answer"] and "12" in tc15["answer"]


def test_phase1_hr_cases_tc16_to_tc20_and_readonly_tc34(phase1_env):
    client, _ = phase1_env
    hr = _login(client, "hr@company.vn")

    # TC-16: HR asking specific employee NV007 late count + work hours (must NOT return 80 company employees!)
    tc16 = client.post(
        "/api/assistant/ask",
        headers=hr,
        json={"question": "Tháng 10/2026 nhân viên NV007 đi muộn bao nhiêu lần và tổng bao nhiêu giờ công?"},
    ).json()
    assert tc16["status"] == "success"
    assert tc16["table"]["rows"][0]["employee_count"] == 1
    assert "NV007" in tc16["answer"] and "8 lần" in tc16["answer"] and "giờ công" in tc16["answer"]

    # HR asking attendance summary for NV007 -> MUST filter to NV007 (1 employee, not 80!)
    hr_nv007_sum = client.post(
        "/api/assistant/ask",
        headers=hr,
        json={"question": "Tổng hợp chấm công của NV007 tháng 10/2026"},
    ).json()
    assert hr_nv007_sum["status"] == "success"
    assert hr_nv007_sum["table"]["rows"][0]["employee_count"] == 1
    assert "NV007" in hr_nv007_sum["answer"]

    # TC-17: Dual-part high severity anomalies AND R8 over-balance
    tc17 = client.post(
        "/api/assistant/ask",
        headers=hr,
        json={"question": "Liệt kê các nhân viên có cảnh báo mức cao (high) và nhân viên đang vượt quỹ phép năm (R8)."},
    ).json()
    assert tc17["status"] == "success"
    assert "R6" in tc17["answer"] and "NV023" in tc17["answer"]
    assert "R8" in tc17["answer"] and "NV052" in tc17["answer"]

    # TC-18: Employee directory summary + department manager for Kỹ thuật
    tc18 = client.post(
        "/api/assistant/ask",
        headers=hr,
        json={"question": "Phòng Kỹ thuật hiện có bao nhiêu nhân sự và ai là Trưởng phòng?"},
    ).json()
    assert tc18["status"] == "success"
    assert tc18["trace"]["tool_name"] == "get_employee_directory_summary"
    assert "16" in tc18["answer"] and "NV003" in tc18["answer"] and "Trần Quốc Hùng" in tc18["answer"]

    # TC-19: Leave statistics filtered strictly to Marketing in 2026-10
    tc19 = client.post(
        "/api/assistant/ask",
        headers=hr,
        json={"question": "Thống kê tình hình nghỉ phép của riêng phòng Marketing trong kỳ 2026-10."},
    ).json()
    assert tc19["status"] == "success"
    assert tc19["trace"]["row_count"] == 1
    assert "Marketing" in tc19["answer"]
    assert "Kinh doanh" not in tc19["answer"]

    # TC-20: Non-existent employee NV999 -> honest insufficient_data (NOT company top 5!)
    tc20 = client.post(
        "/api/assistant/ask",
        headers=hr,
        json={"question": "Nhân viên NV999 trong tháng 10/2026 đi muộn mấy lần?"},
    ).json()
    assert tc20["status"] == "insufficient_data"
    assert "NV999" in tc20["answer"] and "Không tìm thấy" in tc20["answer"]

    # TC-34: Read-only write-action guard (must NOT misroute to get_leave_by_department!)
    tc34 = client.post(
        "/api/assistant/ask",
        headers=hr,
        json={"question": "Hãy tạo giúp tôi một đơn nghỉ phép cho NV007 ngày 25/11/2026"},
    ).json()
    assert tc34["status"] == "blocked"
    assert tc34["trace"]["tool_name"] == "read_only_guard"
    assert "chỉ đọc" in tc34["answer"].lower()


def test_phase1_executive_cases_tc21_to_tc25(phase1_env):
    client, _ = phase1_env
    exec_h = _login(client, "director@company.vn")

    # TC-21: Comprehensive 5-department comparison (on-time, late, leave, anomalies)
    tc21 = client.post(
        "/api/assistant/ask",
        headers=exec_h,
        json={"question": "So sánh toàn diện 5 phòng ban trong tháng 10/2026 về tỷ lệ đúng giờ, đi muộn, nghỉ phép và số cảnh báo R1-R8."},
    ).json()
    assert tc21["status"] == "success"
    assert tc21["trace"]["tool_name"] == "compare_departments_full"
    assert tc21["trace"]["row_count"] == 5
    first_row = tc21["table"]["rows"][0]
    assert "on_time_rate_pct" in first_row and "leave_rate_pct" in first_row and "total_anomalies" in first_row

    # TC-22: 6-month trend (06/2026-11/2026)
    tc22 = client.post(
        "/api/assistant/ask",
        headers=exec_h,
        json={"question": "Xu hướng tỷ lệ đi muộn toàn công ty trong 6 tháng (06/2026–11/2026) biến động ra sao?"},
    ).json()
    assert tc22["status"] == "success"
    assert tc22["trace"]["tool_name"] == "get_attendance_trend"
    assert tc22["trace"]["row_count"] == 6
    assert "2026-06" in tc22["answer"] and "2026-11" in tc22["answer"]

    # TC-23: Executive pending approval queue (requires_executive_approval = 1 -> NV068)
    tc23 = client.post(
        "/api/assistant/ask",
        headers=exec_h,
        json={"question": "Hiện có những đơn nghỉ phép đặc biệt nào đang chờ Ban Điều hành phê duyệt?"},
    ).json()
    assert tc23["status"] == "success"
    assert tc23["trace"]["tool_name"] == "list_leave_requests_detail"
    assert "NV068" in tc23["answer"] and "2026-11-20" in tc23["answer"]

    # TC-24: Department anomaly risk ranking with per-rule breakdown
    tc24 = client.post(
        "/api/assistant/ask",
        headers=exec_h,
        json={"question": "Phòng ban nào có mật độ rủi ro cảnh báo R1-R8 đang mở cao nhất và gồm những loại cảnh báo gì?"},
    ).json()
    assert tc24["status"] == "success"
    assert tc24["trace"]["tool_name"] == "get_anomalies_by_department"
    assert "rule_breakdown" in tc24["table"]["columns"]

    # TC-25: 2-department comparison (Kinh doanh vs Kỹ thuật)
    tc25 = client.post(
        "/api/assistant/ask",
        headers=exec_h,
        json={"question": "So sánh hiệu suất chuyên cần giữa phòng Kinh doanh và phòng Kỹ thuật trong tháng 10/2026."},
    ).json()
    assert tc25["status"] == "success"
    assert tc25["trace"]["tool_name"] == "compare_departments_full"
    assert tc25["trace"]["row_count"] == 2
    dept_names = {r["department_name"] for r in tc25["table"]["rows"]}
    assert dept_names == {"Kinh doanh", "Kỹ thuật"}
