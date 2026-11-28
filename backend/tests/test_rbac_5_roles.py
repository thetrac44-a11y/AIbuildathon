from __future__ import annotations

import io
import sqlite3
from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from app.core.security import REVOKED_JTIS, get_db_dependency, load_authenticated_user
from app.db.connection import get_connection
from app.db.migrations import migrate_rbac_5_roles
from app.db.seed import DEV_DEFAULT_PASSWORD, seed_database
from app.main import app
from app.services.anomaly_service import run_anomaly_scan
from app.services.sql_guard import SQLGuardError, execute_guarded_sql


@pytest.fixture()
def rbac5_env(tmp_path: Path):
    db_file = tmp_path / "rbac_5_roles.db"
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


def _login(client: TestClient, username: str, password: str = DEV_DEFAULT_PASSWORD):
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, f"Login failed for {username}: {resp.text}"
    body = resp.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]


# =============================================================================
# 1. SEED ACCOUNTS & PERMISSION MATRIX VERIFICATION
# =============================================================================

def test_seed_5_roles_and_permissions_loaded(rbac5_env):
    client, db_file = rbac5_env

    # All 5 roles can authenticate via existing JWT mechanism
    for username, expected_role in [
        ("nv007@company.vn", "employee"),
        ("manager.sales@company.vn", "manager"),
        ("hr@company.vn", "hr"),
        ("director@company.vn", "executive"),
        ("admin@company.vn", "admin"),
    ]:
        headers, user = _login(client, username)
        assert user["role"] == expected_role
        assert isinstance(user["permissions"], list) and len(user["permissions"]) >= 5
        me = client.get("/api/auth/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["role"] == expected_role
        assert set(me.json()["permissions"]) == set(user["permissions"])

    # Verify DB roles table has exact 5 roles & no duplicates
    conn = get_connection(db_file, readonly=True)
    try:
        role_codes = {r["role_code"] for r in conn.execute("SELECT role_code FROM roles").fetchall()}
        assert role_codes == {"employee", "manager", "hr", "executive", "admin"}
    finally:
        conn.close()


# =============================================================================
# 2. EMPLOYEE ROLE MATRIX (PASS & FAIL)
# =============================================================================

def test_employee_rbac_matrix_and_cross_user_isolation(rbac5_env):
    client, db_file = rbac5_env
    emp_headers, emp_user = _login(client, "nv007@company.vn")

    # PASS: own attendance, own leave, create leave, own alert, own AI
    att = client.get("/api/attendance?period=2026-10", headers=emp_headers)
    assert att.status_code == 200
    assert all(r["employee_id"] == "NV007" for r in att.json()["items"])

    leaves = client.get("/api/leaves", headers=emp_headers)
    assert leaves.status_code == 200
    assert all(r["employee_id"] == "NV007" for r in leaves.json()["items"])

    create_lv = client.post(
        "/api/leaves",
        headers=emp_headers,
        json={"leave_type": "personal", "from_date": "2026-12-15", "to_date": "2026-12-15", "reason": "Việc gia đình"},
    )
    assert create_lv.status_code == 201
    new_req_id = create_lv.json()["request"]["request_id"]
    assert client.post(f"/api/leaves/{new_req_id}/cancel", headers=emp_headers).status_code == 200

    anom = client.get("/api/anomalies", headers=emp_headers)
    assert anom.status_code == 200
    assert all(a["scope_type"] == "employee" and a["employee_id"] == "NV007" for a in anom.json()["items"])

    # FAIL: other employee attendance, other dept, employee management, accounts, reports, RBAC, system config
    conn = get_connection(db_file, readonly=True)
    other_att_id = conn.execute("SELECT id FROM attendance WHERE employee_id = 'NV015' LIMIT 1").fetchone()["id"]
    conn.close()
    assert client.get(f"/api/attendance/{other_att_id}", headers=emp_headers).status_code == 403
    assert client.get("/api/attendance?department_id=DEPT_TECH", headers=emp_headers).status_code == 403
    assert client.get("/api/employees", headers=emp_headers).status_code == 403
    assert client.get("/api/accounts", headers=emp_headers).status_code == 403
    assert client.get("/api/reports/preview?period=2026-10", headers=emp_headers).status_code == 403
    assert client.get("/api/reports/export/excel?period=2026-10", headers=emp_headers).status_code == 403
    assert client.get("/api/reports/export/pdf?period=2026-10", headers=emp_headers).status_code == 403
    assert client.get("/api/rbac/roles", headers=emp_headers).status_code == 403
    assert client.get("/api/system/config", headers=emp_headers).status_code == 403
    assert client.get("/api/audit/queries", headers=emp_headers).status_code == 403
    assert client.patch(f"/api/attendance/{other_att_id}", headers=emp_headers, json={"status": "present", "reason": "hack"}).status_code == 403

    # AI cross-user leak blocked
    ai_other = client.post("/api/assistant/ask", headers=emp_headers, json={"question": "NV015 tháng 10/2026 đi muộn mấy ngày?"})
    assert ai_other.status_code == 200
    assert ai_other.json()["status"] == "blocked"


# =============================================================================
# 3. MANAGER ROLE MATRIX & CROSS-DEPARTMENT LEAK PROTECTION
# =============================================================================

def test_manager_rbac_matrix_and_cross_department_leak_blocked(rbac5_env):
    client, db_file = rbac5_env
    mgr_tech, _ = _login(client, "manager.tech@company.vn")

    # PASS: own department dashboard, attendance, anomalies, report, AI
    dash = client.get("/api/dashboard/summary?period=2026-10", headers=mgr_tech)
    assert dash.status_code == 200
    assert dash.json()["scope"]["department_id"] == "DEPT_TECH"
    assert dash.json()["kpis"]["total_employees"] == 16

    att = client.get("/api/attendance?period=2026-10", headers=mgr_tech)
    assert att.status_code == 200
    assert all(r["department_id"] == "DEPT_TECH" for r in att.json()["items"])

    rep = client.get("/api/reports/preview?period=2026-10", headers=mgr_tech)
    assert rep.status_code == 200
    assert rep.json()["department_id"] == "DEPT_TECH"

    # PASS: approve own department employee leave (NV025 is DEPT_TECH pending)
    leaves = client.get("/api/leaves", headers=mgr_tech).json()["items"]
    nv025_lv = next(x for x in leaves if x["employee_id"] == "NV025" and x["status"] == "pending")
    assert client.post(
        f"/api/leaves/{nv025_lv['request_id']}/review",
        headers=mgr_tech,
        json={"decision": "approved", "decision_note": "OK"},
    ).status_code == 200

    # FAIL: self-approval blocked
    own_lv = client.post(
        "/api/leaves",
        headers=mgr_tech,
        json={"leave_type": "annual", "from_date": "2026-12-20", "to_date": "2026-12-20", "reason": "Nghỉ cá nhân"},
    )
    assert own_lv.status_code == 201
    own_req_id = own_lv.json()["request"]["request_id"]
    assert client.post(
        f"/api/leaves/{own_req_id}/review",
        headers=mgr_tech,
        json={"decision": "approved", "decision_note": "Tự duyệt"},
    ).status_code == 403

    # FAIL: Cross-department REST, Reports, Exports, AI Assistant & SQL Guard
    assert client.get("/api/dashboard/summary?period=2026-10&department_id=DEPT_SALES", headers=mgr_tech).status_code == 403
    assert client.get("/api/attendance?period=2026-10&department_id=DEPT_SALES", headers=mgr_tech).status_code == 403
    assert client.get("/api/leaves?department_id=DEPT_SALES", headers=mgr_tech).status_code == 403
    assert client.get("/api/anomalies?department_id=DEPT_SALES", headers=mgr_tech).status_code == 403
    assert client.get("/api/reports/preview?period=2026-10&department_id=DEPT_SALES", headers=mgr_tech).status_code == 403
    assert client.get("/api/reports/export/excel?period=2026-10&department_id=DEPT_SALES", headers=mgr_tech).status_code == 403
    assert client.get("/api/reports/export/pdf?period=2026-10&department_id=DEPT_SALES", headers=mgr_tech).status_code == 403

    # Manager Tech asking AI about Sales department MUST be blocked!
    ai_sales = client.post(
        "/api/assistant/ask",
        headers=mgr_tech,
        json={"question": "Cho tôi attendance của phòng Kinh doanh"},
    )
    assert ai_sales.status_code == 200
    assert ai_sales.json()["status"] == "blocked"

    # FAIL: Manager cannot access accounts, roles, system config, import
    assert client.get("/api/accounts", headers=mgr_tech).status_code == 403
    assert client.get("/api/rbac/roles", headers=mgr_tech).status_code == 403
    assert client.get("/api/system/config", headers=mgr_tech).status_code == 403
    assert client.get("/api/imports/logs", headers=mgr_tech).status_code == 403


# =============================================================================
# 4. HR ROLE MATRIX (BUSINESS ADMIN PASS; SYSTEM ADMIN / ESCALATION BLOCKED)
# =============================================================================

def test_hr_rbac_matrix_and_system_admin_boundaries(rbac5_env):
    client, db_file = rbac5_env
    hr_headers, _ = _login(client, "hr@company.vn")

    # PASS: company dashboard, employees, attendance adjustment, import logs, R1-R8, reports, RAG docs, AI all
    assert client.get("/api/dashboard/summary?period=2026-10", headers=hr_headers).status_code == 200
    assert client.get("/api/employees", headers=hr_headers).json()["can_edit"] is True
    assert client.get("/api/imports/logs", headers=hr_headers).status_code == 200
    assert client.get("/api/reports/preview?period=2026-10", headers=hr_headers).status_code == 200
    assert client.get("/api/rag/documents", headers=hr_headers).status_code == 200
    assert client.get("/api/audit/activity", headers=hr_headers).status_code == 200

    # HR attendance adjustment PASS
    conn = get_connection(db_file, readonly=True)
    att_id = conn.execute("SELECT id FROM attendance WHERE employee_id = 'NV007' LIMIT 1").fetchone()["id"]
    conn.close()
    adj = client.patch(
        f"/api/attendance/{att_id}",
        headers=hr_headers,
        json={"check_in": "2026-06-01 08:25:00", "reason": "Điều chỉnh do lỗi máy chấm công"},
    )
    assert adj.status_code == 200
    assert adj.json()["record"]["source"] == "hr_adjusted"

    # FAIL: HR MUST NOT access system dashboard, RBAC role management, system config, kiosk devices, query audit
    assert client.get("/api/admin/system-dashboard", headers=hr_headers).status_code == 403
    assert client.get("/api/rbac/roles", headers=hr_headers).status_code == 403
    assert client.get("/api/rbac/permissions", headers=hr_headers).status_code == 403
    assert client.patch("/api/rbac/roles/hr/permissions", headers=hr_headers, json={"permissions": ["role.manage"]}).status_code == 403
    assert client.get("/api/system/config", headers=hr_headers).status_code == 403
    assert client.patch("/api/system/config", headers=hr_headers, json={"settings": [{"setting_key": "ai.provider", "setting_value": "hack"}]}).status_code == 403
    assert client.get("/api/kiosk/devices", headers=hr_headers).status_code == 403
    assert client.get("/api/audit/queries", headers=hr_headers).status_code == 403

    # FAIL: HR MUST NOT escalate self or others to admin/executive or lock Admin account (USR080)
    assert client.patch("/api/accounts/USR002", headers=hr_headers, json={"role": "admin"}).status_code == 403
    assert client.patch("/api/accounts/USR007", headers=hr_headers, json={"role": "admin"}).status_code == 403
    assert client.patch("/api/accounts/USR007", headers=hr_headers, json={"role": "executive"}).status_code == 403
    assert client.patch("/api/accounts/USR080", headers=hr_headers, json={"is_active": False}).status_code == 403
    assert client.patch("/api/accounts/USR079", headers=hr_headers, json={"is_active": False}).status_code == 403
    assert client.patch("/api/employees/NV007", headers=hr_headers, json={"role": "admin"}).status_code == 403


# =============================================================================
# 5. EXECUTIVE ROLE MATRIX (OVERSIGHT + STRATEGIC AI + EXEC APPROVAL ONLY)
# =============================================================================

def test_executive_rbac_matrix_strategic_ai_and_approval(rbac5_env):
    client, db_file = rbac5_env
    exec_headers, exec_user = _login(client, "director@company.vn")
    assert exec_user["role"] == "executive"

    # PASS: company-wide dashboard + department comparison + monthly trend
    dash = client.get("/api/dashboard/summary?period=2026-10", headers=exec_headers)
    assert dash.status_code == 200
    dash_body = dash.json()
    assert dash_body["kpis"]["total_employees"] == 80
    assert len(dash_body["department_chart"]) == 5
    assert len(dash_body["monthly_trend"]) >= 3

    # PASS: department filter, reports preview + Excel + PDF
    assert client.get("/api/dashboard/summary?period=2026-10&department_id=DEPT_SALES", headers=exec_headers).status_code == 200
    rep = client.get("/api/reports/preview?period=2026-10", headers=exec_headers)
    assert rep.status_code == 200 and rep.json()["kpis"]["employee_count"] == 80
    assert client.get("/api/reports/export/excel?period=2026-10", headers=exec_headers).status_code == 200
    assert client.get("/api/reports/export/pdf?period=2026-10", headers=exec_headers).status_code == 200

    # PASS: read ALL R1-R8 anomalies (can_review=False)
    anom = client.get("/api/anomalies", headers=exec_headers)
    assert anom.status_code == 200
    assert anom.json()["total"] >= 8
    assert anom.json()["can_review"] is False
    first_anom_id = anom.json()["items"][0]["anomaly_id"]

    # PASS: Strategic AI questions grounded in real DB data
    for q, expected_tool in [
        ("Phòng ban nào có tỷ lệ đi muộn cao nhất?", "compare_department_metrics"),
        ("Xu hướng chấm công 3 tháng gần đây thế nào?", "get_attendance_trend"),
        ("Phòng nào có nhiều cảnh báo R1-R8 nhất?", "get_anomalies_by_department"),
        ("Những vấn đề attendance nổi bật hiện tại là gì?", "list_anomalies"),
    ]:
        ai_res = client.post("/api/assistant/ask", headers=exec_headers, json={"question": q})
        assert ai_res.status_code == 200, q
        data = ai_res.json()
        assert data["status"] == "success", (q, data)
        assert data["trace"]["tool_name"] == expected_tool
        assert data["trace"]["row_count"] >= 1

    # PASS: Executive high-level leave approval for requires_executive_approval = true (NV068 seeded)
    exec_leaves = client.get("/api/leaves?requires_executive_approval=true", headers=exec_headers)
    assert exec_leaves.status_code == 200
    assert exec_leaves.json()["total"] >= 1
    exec_lv = exec_leaves.json()["items"][0]
    assert exec_lv["can_review"] is True
    approve_exec = client.post(
        f"/api/leaves/{exec_lv['request_id']}/review",
        headers=exec_headers,
        json={"decision": "approved", "decision_note": "BGĐ phê duyệt"},
    )
    assert approve_exec.status_code == 200

    # FAIL: Executive CANNOT approve regular employee leave (requires_executive_approval = false)
    all_leaves = client.get("/api/leaves?status=pending", headers=exec_headers).json()["items"]
    regular_lv = next(x for x in all_leaves if not x["requires_executive_approval"])
    assert regular_lv["can_review"] is False
    assert client.post(
        f"/api/leaves/{regular_lv['request_id']}/review",
        headers=exec_headers,
        json={"decision": "approved", "decision_note": "Not allowed"},
    ).status_code == 403

    # FAIL: Executive CANNOT adjust attendance, review anomalies, import Excel, manage employees/accounts/roles/system/RAG/kiosk
    conn = get_connection(db_file, readonly=True)
    att_id = conn.execute("SELECT id FROM attendance LIMIT 1").fetchone()["id"]
    conn.close()
    assert client.patch(f"/api/attendance/{att_id}", headers=exec_headers, json={"status": "present", "reason": "nope"}).status_code == 403
    assert client.post(f"/api/anomalies/{first_anom_id}/review", headers=exec_headers, json={"review_status": "confirmed"}).status_code == 403
    assert client.post("/api/anomalies/scan", headers=exec_headers).status_code == 403
    assert client.get("/api/imports/logs", headers=exec_headers).status_code == 403
    assert client.post(
        "/api/imports/preview",
        headers=exec_headers,
        data={"data_type": "attendance"},
        files={"file": ("x.csv", io.BytesIO(b"employee_id\nNV007\n"), "text/csv")},
    ).status_code == 403
    assert client.patch("/api/employees/NV007", headers=exec_headers, json={"position": "Test"}).status_code == 403
    assert client.get("/api/accounts", headers=exec_headers).status_code == 403
    assert client.get("/api/rbac/roles", headers=exec_headers).status_code == 403
    assert client.get("/api/system/config", headers=exec_headers).status_code == 403
    assert client.get("/api/audit/queries", headers=exec_headers).status_code == 403
    assert client.get("/api/kiosk/devices", headers=exec_headers).status_code == 403


# =============================================================================
# 6. ADMIN ROLE MATRIX (TECHNICAL ADMIN PASS; HR BUSINESS DATA BLOCKED!)
# =============================================================================

def test_admin_technical_pass_and_hr_business_blocked_with_last_admin_protection(rbac5_env):
    client, db_file = rbac5_env
    admin_headers, admin_user = _login(client, "admin@company.vn")
    assert admin_user["role"] == "admin"

    # PASS: System Dashboard, Accounts (all 5 roles), RBAC, Audit (activity + queries), RAG, System Config, Kiosk
    sys_dash = client.get("/api/admin/system-dashboard", headers=admin_headers)
    assert sys_dash.status_code == 200
    assert sys_dash.json()["kpis"]["total_accounts"] == 80
    assert sys_dash.json()["kpis"]["roles_count"] == 5

    accts = client.get("/api/accounts", headers=admin_headers)
    assert accts.status_code == 200
    assert accts.json()["total"] == 80
    assert set(accts.json()["assignable_roles"]) == {"employee", "manager", "hr", "executive", "admin"}

    roles_resp = client.get("/api/rbac/roles", headers=admin_headers)
    assert roles_resp.status_code == 200
    assert roles_resp.json()["total"] == 5

    assert client.get("/api/rbac/permissions", headers=admin_headers).status_code == 200
    assert client.get("/api/audit/activity", headers=admin_headers).status_code == 200

    # Generate an AI query as executive first, then verify Admin sees it in query audit log
    exec_headers, _ = _login(client, "director@company.vn")
    client.post("/api/assistant/ask", headers=exec_headers, json={"question": "Phòng ban nào có tỷ lệ đi muộn cao nhất?"})
    q_audit = client.get("/api/audit/queries", headers=admin_headers)
    assert q_audit.status_code == 200
    assert q_audit.json()["total"] >= 1
    latest_q = q_audit.json()["items"][0]
    assert latest_q["role"] == "executive"
    assert latest_q["scope"] == "all"
    assert latest_q["success"] is True

    # RAG management PASS (list, upload, reindex, delete)
    assert client.get("/api/rag/documents", headers=admin_headers).status_code == 200
    up = client.post(
        "/api/rag/documents",
        headers=admin_headers,
        json={
            "title": "Quy định làm thêm giờ 2026",
            "original_file_name": "ot_policy.md",
            "document_type": "policy",
            "version_label": "v1.0",
            "content": "Điều 1. Nhân viên làm thêm giờ cuối tuần cần có đơn OT được quản lý phê duyệt trước 24 giờ.",
        },
    )
    assert up.status_code == 201
    doc_id = up.json()["document_id"]
    assert client.post(f"/api/rag/documents/{doc_id}/reindex", headers=admin_headers).status_code == 200
    assert client.delete(f"/api/rag/documents/{doc_id}", headers=admin_headers).status_code == 200

    # System Config PASS + secret rejection guard
    cfg = client.get("/api/system/config", headers=admin_headers)
    assert cfg.status_code == 200
    assert client.patch(
        "/api/system/config",
        headers=admin_headers,
        json={"settings": [{"setting_key": "kiosk.similarity_threshold", "setting_value": "0.65"}]},
    ).status_code == 200
    # Must reject secret keys
    assert client.patch(
        "/api/system/config",
        headers=admin_headers,
        json={"settings": [{"setting_key": "openai_api_key", "setting_value": "sk-fake"}]},
    ).status_code == 400

    # Kiosk devices PASS
    assert client.get("/api/kiosk/devices", headers=admin_headers).status_code == 200
    assert client.post(
        "/api/kiosk/devices",
        headers=admin_headers,
        json={"kiosk_device_id": "KIOSK-HCM-01", "device_name": "Sảnh HCM", "location_name": "Tầng 1", "branch_name": "CN HCM"},
    ).status_code == 201
    assert client.patch("/api/kiosk/devices/KIOSK-HCM-01", headers=admin_headers, json={"is_active": False}).status_code == 200

    # LAST-ACTIVE-ADMIN PROTECTION (cannot self-lock or demote last active admin!)
    lock_last_admin = client.patch("/api/accounts/USR080", headers=admin_headers, json={"is_active": False})
    assert lock_last_admin.status_code == 400
    demote_last_admin = client.patch("/api/accounts/USR080", headers=admin_headers, json={"role": "hr"})
    assert demote_last_admin.status_code == 400
    # Cannot strip core admin permissions from admin role
    strip_admin = client.patch("/api/rbac/roles/admin/permissions", headers=admin_headers, json={"permissions": ["profile.read.self"]})
    assert strip_admin.status_code == 400

    # FAIL: Admin MUST NOT access HR business endpoints or HR AI / SQL Guard by default!
    conn = get_connection(db_file, readonly=True)
    att_id = conn.execute("SELECT id FROM attendance LIMIT 1").fetchone()["id"]
    lv_id = conn.execute("SELECT request_id FROM leave_requests WHERE status = 'pending' LIMIT 1").fetchone()["request_id"]
    anom_id = conn.execute("SELECT anomaly_id FROM anomalies LIMIT 1").fetchone()["anomaly_id"]
    admin_db_user = load_authenticated_user(conn, "USR080")
    conn.close()
    assert admin_db_user is not None

    assert client.get("/api/dashboard/summary?period=2026-10", headers=admin_headers).status_code == 403
    assert client.get("/api/attendance?period=2026-10", headers=admin_headers).status_code == 403
    assert client.get(f"/api/attendance/{att_id}", headers=admin_headers).status_code == 403
    assert client.patch(f"/api/attendance/{att_id}", headers=admin_headers, json={"status": "present", "reason": "admin attempt"}).status_code == 403
    assert client.get("/api/leaves", headers=admin_headers).status_code == 403
    assert client.post(f"/api/leaves/{lv_id}/review", headers=admin_headers, json={"decision": "approved"}).status_code == 403
    assert client.get("/api/anomalies", headers=admin_headers).status_code == 403
    assert client.post(f"/api/anomalies/{anom_id}/review", headers=admin_headers, json={"review_status": "confirmed"}).status_code == 403
    assert client.get("/api/employees", headers=admin_headers).status_code == 403
    assert client.get("/api/employees/NV007", headers=admin_headers).status_code == 403
    assert client.get("/api/reports/preview?period=2026-10", headers=admin_headers).status_code == 403
    assert client.get("/api/reports/export/excel?period=2026-10", headers=admin_headers).status_code == 403
    assert client.get("/api/reports/export/pdf?period=2026-10", headers=admin_headers).status_code == 403
    assert client.get("/api/imports/logs", headers=admin_headers).status_code == 403
    assert client.post("/api/assistant/ask", headers=admin_headers, json={"question": "Phòng nào đi muộn cao nhất?"}).status_code == 403

    # Direct SQL Guard call as Admin MUST also raise SQLGuardError (defense-in-depth)
    with pytest.raises(SQLGuardError):
        execute_guarded_sql(db_file, admin_db_user, "SELECT * FROM v_employees")


# =============================================================================
# 7. NON-DESTRUCTIVE LEGACY 3-ROLE -> 5-ROLE MIGRATION SAFETY TEST
# =============================================================================

def test_non_destructive_legacy_3role_sqlite_migration(tmp_path: Path):
    """Verify migrating an existing 3-role SQLite database preserves 100% of rows and upgrades cleanly to 5 roles."""
    legacy_db = tmp_path / "legacy_3role.db"
    conn = sqlite3.connect(str(legacy_db))
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE departments (department_id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE);
        CREATE TABLE employees (
            employee_id TEXT PRIMARY KEY, full_name TEXT NOT NULL, department_id TEXT NOT NULL,
            position TEXT NOT NULL, manager_id TEXT NULL, start_date TEXT NOT NULL,
            annual_leave_balance REAL NOT NULL DEFAULT 12.0,
            role TEXT NOT NULL CHECK (role IN ('employee', 'manager', 'hr')),
            employment_status TEXT NOT NULL DEFAULT 'active', email TEXT UNIQUE, phone TEXT NULL
        );
        CREATE TABLE users (
            user_id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
            employee_id TEXT NOT NULL UNIQUE, is_active INTEGER NOT NULL DEFAULT 1,
            last_login_at TEXT NULL, must_change_password INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now'))
        );
        CREATE TABLE leave_requests (
            request_id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT NOT NULL,
            leave_type TEXT NOT NULL, from_date TEXT NOT NULL, to_date TEXT NOT NULL,
            reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
            reviewed_by TEXT NULL, reviewed_at TEXT NULL, decision_note TEXT NULL, cancelled_at TEXT NULL
        );
        CREATE TABLE query_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, asked_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
            user_id TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN ('employee', 'manager', 'hr')),
            question TEXT NOT NULL, tool_name TEXT NULL, sql_text TEXT NULL,
            row_count INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL
        );
        INSERT INTO departments VALUES ('DEPT_OPS', 'Vận hành');
        INSERT INTO employees VALUES ('NV001', 'Old Employee', 'DEPT_OPS', 'NV', NULL, '2024-01-01', 12.0, 'employee', 'active', 'nv001@company.vn', NULL);
        INSERT INTO users (user_id, username, password_hash, employee_id) VALUES ('USR001', 'nv001@company.vn', '$2b$04$dummyhashdummyhashdummyhashdummyhashdummyhashdummy', 'NV001');
        INSERT INTO query_audit_log (user_id, role, question, status) VALUES ('USR001', 'employee', 'Legacy question', 'success');
        """
    )
    conn.commit()
    conn.close()

    res = migrate_rbac_5_roles(db_path=legacy_db, seed_demo_accounts=True)
    assert res["schema"]["engine"] == "sqlite"

    c2 = get_connection(legacy_db, readonly=True)
    try:
        # Legacy data 100% preserved
        assert c2.execute("SELECT full_name FROM employees WHERE employee_id = 'NV001'").fetchone()[0] == "Old Employee"
        assert c2.execute("SELECT question FROM query_audit_log WHERE user_id = 'USR001'").fetchone()[0] == "Legacy question"
        # New 5-role accounts & tables created
        assert c2.execute("SELECT role FROM employees WHERE email = 'admin@company.vn'").fetchone()[0] == "admin"
        assert c2.execute("SELECT role FROM employees WHERE email = 'director@company.vn'").fetchone()[0] == "executive"
        assert c2.execute("SELECT COUNT(*) FROM roles").fetchone()[0] == 5
        assert c2.execute("SELECT COUNT(*) FROM permissions").fetchone()[0] >= 40
    finally:
        c2.close()
