import pytest
from fastapi.testclient import TestClient

from app.core.security import REVOKED_JTIS, get_db_dependency
from app.db.connection import get_connection
from app.db.seed import DEV_DEFAULT_PASSWORD, seed_database
from app.main import app


@pytest.fixture()
def client_with_db(tmp_path):
    db_file = tmp_path / "rbac_test.db"
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
        yield client
    app.dependency_overrides.clear()


def _login(client: TestClient, username: str, password: str = DEV_DEFAULT_PASSWORD):
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, resp.json()


def test_login_me_logout_and_change_password(client_with_db: TestClient):
    # Unauthenticated request rejected
    assert client_with_db.get("/api/auth/me").status_code == 401

    # Invalid password rejected
    bad = client_with_db.post("/api/auth/login", json={"username": "hr@company.vn", "password": "wrong"})
    assert bad.status_code == 401

    # Login succeeds
    headers, login_data = _login(client_with_db, "nv007@company.vn")
    assert login_data["user"]["employee_id"] == "NV007"
    assert login_data["user"]["role"] == "employee"

    # /api/auth/me returns profile
    me = client_with_db.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["employee_id"] == "NV007"

    # Change password works
    chg = client_with_db.post(
        "/api/auth/change-password",
        headers=headers,
        json={"current_password": DEV_DEFAULT_PASSWORD, "new_password": "NewPassword@456"},
    )
    assert chg.status_code == 200

    # Logout revokes current token
    out = client_with_db.post("/api/auth/logout", headers=headers)
    assert out.status_code == 200
    assert client_with_db.get("/api/auth/me", headers=headers).status_code == 401

    # Login with new password succeeds
    new_headers, _ = _login(client_with_db, "nv007@company.vn", "NewPassword@456")
    assert client_with_db.get("/api/auth/me", headers=new_headers).status_code == 200


def test_employee_scope_and_privilege_escalation_blocked(client_with_db: TestClient):
    emp_headers, _ = _login(client_with_db, "nv007@company.vn")

    # Employee dashboard only shows own metrics (1 employee, 8 late days in Oct 2026 per S1)
    dash = client_with_db.get("/api/dashboard/summary?period=2026-10", headers=emp_headers)
    assert dash.status_code == 200
    body = dash.json()
    assert body["kpis"]["total_employees"] == 1
    assert body["kpis"]["late_days"] == 8
    assert body["scope"]["employee_id"] == "NV007"

    # Employee cannot widen scope by passing department_id in URL
    assert client_with_db.get("/api/dashboard/summary?period=2026-10&department_id=DEPT_TECH", headers=emp_headers).status_code == 403

    # Employee cannot access employee list, other employee details, accounts, or audit logs
    assert client_with_db.get("/api/employees", headers=emp_headers).status_code == 403
    assert client_with_db.get("/api/employees/NV015", headers=emp_headers).status_code == 403
    assert client_with_db.get("/api/employees/NV007", headers=emp_headers).status_code == 200
    assert client_with_db.get("/api/accounts", headers=emp_headers).status_code == 403
    assert client_with_db.get("/api/audit/activity", headers=emp_headers).status_code == 403

    # Client attempt to escalate role via PATCH /api/profile is rejected (422 extra=forbid)
    escalate = client_with_db.patch(
        "/api/profile",
        headers=emp_headers,
        json={"phone": "0999888777", "role": "hr", "department_id": "DEPT_HR"},
    )
    assert escalate.status_code == 422

    # Safe contact field update succeeds without changing role
    safe = client_with_db.patch("/api/profile", headers=emp_headers, json={"phone": "0999888777"})
    assert safe.status_code == 200
    assert safe.json()["phone"] == "0999888777"
    assert safe.json()["role"] == "employee"


def test_manager_scope_enforced_and_hr_writes_blocked(client_with_db: TestClient):
    mgr_headers, _ = _login(client_with_db, "manager.sales@company.vn")

    # Manager dashboard sees only DEPT_SALES (16 employees)
    dash = client_with_db.get("/api/dashboard/summary?period=2026-10", headers=mgr_headers)
    assert dash.status_code == 200
    assert dash.json()["kpis"]["total_employees"] == 16
    assert dash.json()["scope"]["department_id"] == "DEPT_SALES"

    # Manager trying to switch department_id in URL to DEPT_TECH gets 403
    assert client_with_db.get("/api/dashboard/summary?period=2026-10&department_id=DEPT_TECH", headers=mgr_headers).status_code == 403
    assert client_with_db.get("/api/employees?department_id=DEPT_TECH", headers=mgr_headers).status_code == 403

    # Manager read-only employee list sees only DEPT_SALES (16 employees, can_edit=False)
    emp_list = client_with_db.get("/api/employees", headers=mgr_headers)
    assert emp_list.status_code == 200
    assert emp_list.json()["total"] == 16
    assert emp_list.json()["can_edit"] is False
    assert all(e["department_id"] == "DEPT_SALES" for e in emp_list.json()["items"])

    # Manager cannot view employee from another department
    assert client_with_db.get("/api/employees/NV023", headers=mgr_headers).status_code == 403
    # Manager CAN view employee from own department
    assert client_with_db.get("/api/employees/NV007", headers=mgr_headers).status_code == 200

    # Manager cannot write employees or manage accounts
    assert client_with_db.patch("/api/employees/NV007", headers=mgr_headers, json={"position": "Hacked"}).status_code == 403
    assert client_with_db.get("/api/accounts", headers=mgr_headers).status_code == 403


def test_hr_full_access_and_last_hr_account_protection(client_with_db: TestClient):
    hr_headers, _ = _login(client_with_db, "hr@company.vn")

    # HR sees all 80 employees across 5 departments
    dash = client_with_db.get("/api/dashboard/summary?period=2026-10", headers=hr_headers)
    assert dash.status_code == 200
    assert dash.json()["kpis"]["total_employees"] == 80

    # HR can filter to specific department
    tech_dash = client_with_db.get("/api/dashboard/summary?period=2026-10&department_id=DEPT_TECH", headers=hr_headers)
    assert tech_dash.status_code == 200
    assert tech_dash.json()["kpis"]["total_employees"] == 16

    # HR can lock secondary HR account (USR006)
    lock_hr2 = client_with_db.patch("/api/accounts/USR006", headers=hr_headers, json={"is_active": False})
    assert lock_hr2.status_code == 200

    # Trying to lock or demote the LAST active HR account (USR002) MUST be blocked (400)
    lock_last_hr = client_with_db.patch("/api/accounts/USR002", headers=hr_headers, json={"is_active": False})
    assert lock_last_hr.status_code == 400
    demote_last_hr = client_with_db.patch("/api/accounts/USR002", headers=hr_headers, json={"role": "manager"})
    assert demote_last_hr.status_code == 400

    # Role change on another user takes effect immediately on their active token
    emp_headers, _ = _login(client_with_db, "nv007@company.vn")
    assert client_with_db.get("/api/accounts", headers=emp_headers).status_code == 403

    # Lock NV007's account (USR007) -> immediate 401 on existing token
    lock_nv007 = client_with_db.patch("/api/accounts/USR007", headers=hr_headers, json={"is_active": False})
    assert lock_nv007.status_code == 200
    assert client_with_db.get("/api/auth/me", headers=emp_headers).status_code == 401
