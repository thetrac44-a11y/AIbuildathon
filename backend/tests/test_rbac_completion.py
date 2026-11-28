from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from app.core.security import REVOKED_JTIS, get_db_dependency
from app.db.connection import get_connection
from app.db.seed import DEV_DEFAULT_PASSWORD, seed_database
from app.main import app
from app.services.anomaly_service import run_anomaly_scan


@pytest.fixture()
def rbac_complete_env(tmp_path: Path):
    db_file = tmp_path / "rbac_completion.db"
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


def test_live_role_demotion_and_permission_revocation_on_existing_token(rbac_complete_env):
    """Revoking a user's role or permission MUST take effect immediately on an existing valid JWT."""
    client, _ = rbac_complete_env
    admin = _login(client, "admin@company.vn")
    mgr_sales = _login(client, "manager.sales@company.vn")

    # Before demotion: Manager Sales can access department report & employee list
    assert client.get("/api/reports/preview?period=2026-10", headers=mgr_sales).status_code == 200
    assert client.get("/api/employees", headers=mgr_sales).status_code == 200

    # Admin demotes manager.sales (USR001) to employee while JWT is still active
    demote = client.patch("/api/accounts/USR001", headers=admin, json={"role": "employee"})
    assert demote.status_code == 200

    # Existing JWT immediately loses manager capabilities & scope
    me = client.get("/api/auth/me", headers=mgr_sales).json()
    assert me["role"] == "employee"
    assert client.get("/api/reports/preview?period=2026-10", headers=mgr_sales).status_code == 403
    assert client.get("/api/employees", headers=mgr_sales).status_code == 403
    dash = client.get("/api/dashboard/summary?period=2026-10", headers=mgr_sales).json()
    assert dash["kpis"]["total_employees"] == 1
    assert dash["scope"]["employee_id"] == "NV001"


def test_live_department_transfer_immediately_updates_data_scope(rbac_complete_env):
    """Moving a Manager from DEPT_SALES to DEPT_TECH MUST immediately revoke DEPT_SALES scope on existing JWT."""
    client, _ = rbac_complete_env
    hr = _login(client, "hr@company.vn")
    mgr = _login(client, "manager.sales@company.vn")

    # Initially scoped to DEPT_SALES
    assert client.get("/api/dashboard/summary?period=2026-10", headers=mgr).json()["scope"]["department_id"] == "DEPT_SALES"
    assert client.get("/api/employees?department_id=DEPT_TECH", headers=mgr).status_code == 403

    # HR transfers NV001 to DEPT_TECH
    move = client.patch("/api/employees/NV001", headers=hr, json={"department_id": "DEPT_TECH"})
    assert move.status_code == 200

    # Existing JWT immediately reflects DEPT_TECH and gets 403 for old DEPT_SALES!
    assert client.get("/api/dashboard/summary?period=2026-10", headers=mgr).json()["scope"]["department_id"] == "DEPT_TECH"
    assert client.get("/api/dashboard/summary?period=2026-10&department_id=DEPT_SALES", headers=mgr).status_code == 403
    assert client.get("/api/reports/preview?period=2026-10&department_id=DEPT_SALES", headers=mgr).status_code == 403
    emps = client.get("/api/employees", headers=mgr).json()["items"]
    assert len(emps) > 0 and all(e["department_id"] == "DEPT_TECH" for e in emps)

    # AI Assistant also blocks old department immediately
    ai_old = client.post("/api/assistant/ask", headers=mgr, json={"question": "Tổng hợp chấm công phòng Kinh doanh tháng 10/2026"})
    assert ai_old.status_code == 200
    assert ai_old.json()["status"] == "blocked"


def test_defense_in_depth_anomalies_reports_and_self_attendance_adjustment(rbac_complete_env):
    """Verify RBAC-GAP-02, RBAC-GAP-03 & RBAC-GAP-06 defense-in-depth protections."""
    client, db_file = rbac_complete_env
    admin = _login(client, "admin@company.vn")
    hr = _login(client, "hr@company.vn")
    exec_h = _login(client, "director@company.vn")

    conn = get_connection(db_file, readonly=True)
    hr_own_att = conn.execute("SELECT id, work_date FROM attendance WHERE employee_id = 'NV002' LIMIT 1").fetchone()
    any_anom = conn.execute("SELECT anomaly_id FROM anomalies LIMIT 1").fetchone()
    conn.close()
    assert hr_own_att is not None and any_anom is not None

    # HR MUST NOT adjust their OWN attendance record (self-adjustment blocked with 403)
    self_adj = client.patch(
        f"/api/attendance/{hr_own_att['id']}",
        headers=hr,
        json={"check_in": f"{hr_own_att['work_date']} 08:25:00", "reason": "Tự sửa công bản thân"},
    )
    assert self_adj.status_code == 403

    # Even if Admin accidentally assigns anomaly.read.self + anomaly.review to admin role -> STILL blocked 403!
    roles = client.get("/api/rbac/roles", headers=admin).json()["items"]
    admin_orig = next(r["permissions"] for r in roles if r["role_code"] == "admin")
    assert (
        client.patch(
            "/api/rbac/roles/admin/permissions",
            headers=admin,
            json={"permissions": sorted(set([*admin_orig, "anomaly.read.self", "anomaly.review", "report.read.all"]))},
        ).status_code
        == 200
    )
    assert client.get(f"/api/anomalies/{any_anom['anomaly_id']}", headers=admin).status_code == 403
    assert client.post("/api/anomalies/scan", headers=admin).status_code == 403
    assert client.post(
        f"/api/anomalies/{any_anom['anomaly_id']}/review",
        headers=admin,
        json={"review_status": "confirmed"},
    ).status_code == 403
    assert client.get("/api/reports/preview?period=2026-10", headers=admin).status_code == 403

    # Narrowing Executive report permission from report.read.all -> report.read.department constrains report scope
    exec_orig = next(r["permissions"] for r in roles if r["role_code"] == "executive")
    narrowed_exec = [p for p in exec_orig if p != "report.read.all"] + ["report.read.department"]
    assert client.patch("/api/rbac/roles/executive/permissions", headers=admin, json={"permissions": narrowed_exec}).status_code == 200
    assert client.get("/api/reports/preview?period=2026-10&department_id=DEPT_SALES", headers=exec_h).status_code == 403
    narrowed_rep = client.get("/api/reports/preview?period=2026-10", headers=exec_h)
    assert narrowed_rep.status_code == 200
    assert narrowed_rep.json()["department_id"] == "DEPT_OPS"


def test_manager_personal_self_service_independent_from_manager_role(rbac_complete_env):
    """Manager's personal profile & own leave submission/cancellation work independently without self-approval."""
    client, _ = rbac_complete_env
    mgr = _login(client, "manager.sales@company.vn")

    # Manager updates own phone via /api/profile without altering role
    prof = client.patch("/api/profile", headers=mgr, json={"phone": "0912345678"})
    assert prof.status_code == 200
    assert prof.json()["phone"] == "0912345678"
    assert prof.json()["role"] == "manager"

    # Manager creates own leave, cannot self-approve, CAN cancel own pending leave
    lv = client.post(
        "/api/leaves",
        headers=mgr,
        json={"leave_type": "personal", "from_date": "2026-12-22", "to_date": "2026-12-22", "reason": "Việc cá nhân"},
    )
    assert lv.status_code == 201
    req_id = lv.json()["request"]["request_id"]
    assert client.post(f"/api/leaves/{req_id}/review", headers=mgr, json={"decision": "approved"}).status_code == 403
    assert client.post(f"/api/leaves/{req_id}/cancel", headers=mgr).status_code == 200


def test_allowed_screens_synced_for_executive_and_admin(rbac_complete_env):
    """/api/auth/me allowed_screens matches frontend sidebar separation for Executive & Admin."""
    client, _ = rbac_complete_env
    exec_h = _login(client, "director@company.vn")
    admin_h = _login(client, "admin@company.vn")

    exec_screens = set(client.get("/api/auth/me", headers=exec_h).json()["allowed_screens"])
    assert {"dashboard", "anomalies", "reports", "assistant", "leaves", "profile"}.issubset(exec_screens)
    assert "attendance" not in exec_screens
    assert "employees" not in exec_screens
    assert "accounts" not in exec_screens
    assert "import" not in exec_screens
    assert "rbac" not in exec_screens

    admin_screens = set(client.get("/api/auth/me", headers=admin_h).json()["allowed_screens"])
    assert {"system_dashboard", "accounts", "rbac", "audit", "rag", "system_config", "kiosk", "profile"}.issubset(admin_screens)
    assert "attendance" not in admin_screens
    assert "leaves" not in admin_screens
    assert "reports" not in admin_screens
    assert "dashboard" not in admin_screens
