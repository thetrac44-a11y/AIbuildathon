import io
import pytest
from fastapi.testclient import TestClient

from app.core.security import REVOKED_JTIS, get_db_dependency
from app.db.connection import get_connection
from app.db.seed import DEV_DEFAULT_PASSWORD, seed_database
from app.main import app
from app.services.import_service import STAGING_BATCHES, confirm_staged_import, stage_and_validate_import


@pytest.fixture()
def test_env(tmp_path):
    db_file = tmp_path / "ops_test.db"
    seed_database(db_path=db_file, reset=True)
    REVOKED_JTIS.clear()
    STAGING_BATCHES.clear()

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


def test_attendance_scoping_and_filters(test_env):
    client, _ = test_env
    emp_headers = _login(client, "nv007@company.vn")
    mgr_headers = _login(client, "manager.sales@company.vn")
    hr_headers = _login(client, "hr@company.vn")

    # Employee sees only NV007 late days in Oct 2026 (8 days per S1)
    r_emp = client.get("/api/attendance?period=2026-10&status=late", headers=emp_headers)
    assert r_emp.status_code == 200
    assert r_emp.json()["total"] == 8
    assert all(row["employee_id"] == "NV007" for row in r_emp.json()["items"])

    # Manager sees only DEPT_SALES missing_punch in Sep 2026 (NV015 has 4 days per S2)
    r_mgr = client.get("/api/attendance?period=2026-09&status=missing_punch", headers=mgr_headers)
    assert r_mgr.status_code == 200
    assert r_mgr.json()["total"] == 4
    assert all(row["department_id"] == "DEPT_SALES" for row in r_mgr.json()["items"])

    # Manager cannot filter another department
    assert client.get("/api/attendance?period=2026-10&department_id=DEPT_TECH", headers=mgr_headers).status_code == 403

    # HR sees all departments
    r_hr = client.get("/api/attendance?period=2026-10&page_size=200", headers=hr_headers)
    assert r_hr.status_code == 200
    assert r_hr.json()["total"] > 1000


def test_leave_workflow_approve_reject_cancel_and_rbac(test_env):
    client, _ = test_env
    emp_headers = _login(client, "nv007@company.vn")
    mgr_sales_headers = _login(client, "manager.sales@company.vn")
    mgr_tech_headers = _login(client, "manager.tech@company.vn")
    hr_headers = _login(client, "hr@company.vn")

    # Invalid date range rejected
    bad_date = client.post(
        "/api/leaves",
        headers=emp_headers,
        json={"leave_type": "annual", "from_date": "2026-12-10", "to_date": "2026-12-08", "reason": "Test invalid"},
    )
    assert bad_date.status_code == 400

    # Exceeding annual balance (15 days > 12) rejected
    over_bal = client.post(
        "/api/leaves",
        headers=emp_headers,
        json={"leave_type": "annual", "from_date": "2026-12-01", "to_date": "2026-12-15", "reason": "Quá quỹ phép"},
    )
    assert over_bal.status_code == 400

    # Valid leave request created as pending (does NOT deduct balance yet)
    bal_before = client.get("/api/leaves", headers=emp_headers).json()["my_balance"]["used_annual_leave"]
    create_resp = client.post(
        "/api/leaves",
        headers=emp_headers,
        json={"leave_type": "annual", "from_date": "2026-12-02", "to_date": "2026-12-03", "reason": "Nghỉ phép gia đình"},
    )
    assert create_resp.status_code == 201
    req_id = create_resp.json()["request"]["request_id"]
    assert create_resp.json()["request"]["status"] == "pending"
    assert create_resp.json()["request"]["leave_days"] == 2
    assert client.get("/api/leaves", headers=emp_headers).json()["my_balance"]["used_annual_leave"] == bal_before

    # Employee cannot approve own request
    assert client.post(f"/api/leaves/{req_id}/review", headers=emp_headers, json={"decision": "approved"}).status_code == 403

    # Manager of ANOTHER department (Tech) cannot review Sales employee request
    assert client.post(f"/api/leaves/{req_id}/review", headers=mgr_tech_headers, json={"decision": "approved"}).status_code == 403

    # Reject without decision_note fails (400)
    assert client.post(f"/api/leaves/{req_id}/review", headers=mgr_sales_headers, json={"decision": "rejected", "decision_note": "   "}).status_code == 400

    # Manager of Sales approves -> balance updates by +2 & timeline logged
    approve_resp = client.post(
        f"/api/leaves/{req_id}/review",
        headers=mgr_sales_headers,
        json={"decision": "approved", "decision_note": "Đồng ý"},
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["request"]["status"] == "approved"
    assert client.get("/api/leaves", headers=emp_headers).json()["my_balance"]["used_annual_leave"] == bal_before + 2

    detail = client.get(f"/api/leaves/{req_id}", headers=emp_headers).json()
    assert len(detail["timeline"]) == 2
    assert [t["action"] for t in detail["timeline"]] == ["submit", "approve"]

    # Manager creates own leave request -> Manager CANNOT self-approve (403); HR CAN approve
    mgr_req = client.post(
        "/api/leaves",
        headers=mgr_sales_headers,
        json={"leave_type": "annual", "from_date": "2026-12-07", "to_date": "2026-12-07", "reason": "Trưởng phòng nghỉ phép"},
    )
    assert mgr_req.status_code == 201
    mgr_req_id = mgr_req.json()["request"]["request_id"]
    assert client.post(f"/api/leaves/{mgr_req_id}/review", headers=mgr_sales_headers, json={"decision": "approved"}).status_code == 403
    assert client.post(f"/api/leaves/{mgr_req_id}/review", headers=hr_headers, json={"decision": "approved", "decision_note": "HR duyệt"}).status_code == 200

    # Employee creates another pending leave and cancels it cleanly
    req2 = client.post(
        "/api/leaves",
        headers=emp_headers,
        json={"leave_type": "personal", "from_date": "2026-12-10", "to_date": "2026-12-10", "reason": "Việc riêng"},
    )
    req2_id = req2.json()["request"]["request_id"]
    cancel_resp = client.post(f"/api/leaves/{req2_id}/cancel", headers=emp_headers)
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["new_status"] == "cancelled"


def test_import_staging_duplicate_protection_and_transaction_rollback(test_env):
    client, db_file = test_env
    emp_headers = _login(client, "nv007@company.vn")
    mgr_headers = _login(client, "manager.sales@company.vn")
    hr_headers = _login(client, "hr@company.vn")

    # Non-HR blocked from import endpoints
    assert client.get("/api/imports/template/attendance", headers=emp_headers).status_code == 403
    assert client.get("/api/imports/template/attendance", headers=mgr_headers).status_code == 403

    # Template download works for HR
    tpl = client.get("/api/imports/template/attendance", headers=hr_headers)
    assert tpl.status_code == 200
    assert len(tpl.content) > 100

    # Upload CSV containing: 1 valid new date, 1 duplicate existing date, 1 invalid unknown emp, 1 formula injection
    csv_payload = (
        "employee_id,work_date,check_in,check_out,status,source\n"
        "NV007,2026-12-01,2026-12-01 08:25:00,2026-12-01 17:35:00,present,import_csv\n"
        "NV007,2026-10-02,2026-10-02 08:20:00,2026-10-02 17:30:00,present,import_csv\n"
        "NV999,2026-12-01,2026-12-01 08:25:00,2026-12-01 17:35:00,present,import_csv\n"
        "NV007,2026-12-04,2026-12-04 08:25:00,2026-12-04 17:35:00,present,=HYPERLINK(\"http://evil\")\n"
    ).encode("utf-8")

    preview = client.post(
        "/api/imports/preview",
        headers=hr_headers,
        data={"data_type": "attendance"},
        files={"file": ("dec_att.csv", io.BytesIO(csv_payload), "text/csv")},
    )
    assert preview.status_code == 200, preview.text
    p_data = preview.json()
    assert p_data["summary"]["rows_total"] == 4
    assert p_data["summary"]["rows_valid"] == 1
    assert p_data["summary"]["rows_duplicate"] == 1
    assert p_data["summary"]["rows_error"] == 2
    batch_id = p_data["batch_id"]

    # Verify DB has NOT been modified yet before confirmation
    conn = get_connection(db_file)
    try:
        before_cnt = conn.execute(
            "SELECT COUNT(*) FROM attendance WHERE employee_id = 'NV007' AND work_date = '2026-12-01'"
        ).fetchone()[0]
        assert before_cnt == 0
    finally:
        conn.close()

    # Download errors CSV succeeds
    err_csv = client.get(f"/api/imports/errors/{batch_id}", headers=hr_headers)
    assert err_csv.status_code == 200
    assert "NV999" in err_csv.text

    # Confirm with duplicate_policy='skip' -> inserts 1 valid row, skips 1 duplicate (does not overwrite 2026-10-02!)
    confirm = client.post(
        f"/api/imports/confirm/{batch_id}",
        headers=hr_headers,
        json={"duplicate_policy": "skip"},
    )
    assert confirm.status_code == 200
    assert confirm.json()["inserted"] == 1
    assert confirm.json()["skipped"] == 1

    # Verify transaction rollback leaves DB clean on mid-transaction failure
    conn = get_connection(db_file)
    try:
        csv_rollback = (
            "employee_id,work_date,check_in,check_out,status,source\n"
            "NV007,2026-12-15,2026-12-15 08:20:00,2026-12-15 17:30:00,present,import_csv\n"
        ).encode("utf-8")
        rb_preview = stage_and_validate_import(conn, "USR002", "rb.csv", "attendance", csv_rollback)
        with pytest.raises(RuntimeError):
            confirm_staged_import(conn, rb_preview["batch_id"], "USR002", duplicate_policy="skip", force_fail_for_test=True)

        # Row must NOT exist after rollback, and import_logs status must be 'failed'
        after_rb = conn.execute(
            "SELECT COUNT(*) FROM attendance WHERE employee_id = 'NV007' AND work_date = '2026-12-15'"
        ).fetchone()[0]
        assert after_rb == 0
        log_status = conn.execute(
            "SELECT status FROM import_logs WHERE file_name = 'rb.csv' ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        assert log_status == "failed"
    finally:
        conn.close()
