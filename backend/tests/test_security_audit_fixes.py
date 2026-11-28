from __future__ import annotations

import datetime
import io
from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from app.core.security import REVOKED_JTIS, get_db_dependency
from app.db.connection import get_connection
from app.db.seed import DEV_DEFAULT_PASSWORD, seed_database
from app.main import app
from app.services.anomaly_service import run_anomaly_scan
from app.services.import_service import STAGING_BATCHES, confirm_staged_import, stage_and_validate_import
from app.services.sql_guard import SQLGuardError, validate_readonly_sql


@pytest.fixture()
def audit_env(tmp_path: Path):
    db_file = tmp_path / "security_audit.db"
    seed_database(db_path=db_file, reset=True)
    conn = get_connection(db_file, readonly=False)
    run_anomaly_scan(conn, period=None)
    conn.close()
    REVOKED_JTIS.clear()
    STAGING_BATCHES.clear()

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


def test_audit_sec01_employee_list_never_leaks_even_if_misconfigured(audit_env):
    client, _ = audit_env
    admin = _login(client, "admin@company.vn")
    emp = _login(client, "nv007@company.vn")
    mgr = _login(client, "manager.sales@company.vn")
    hr = _login(client, "hr@company.vn")
    exec_h = _login(client, "director@company.vn")

    # Even if Admin accidentally assigns employee.read.all to employee role, employee MUST STILL get 403!
    roles_before = client.get("/api/rbac/roles", headers=admin).json()["items"]
    emp_orig_perms = next(r["permissions"] for r in roles_before if r["role_code"] == "employee")
    grant_resp = client.patch(
        "/api/rbac/roles/employee/permissions",
        headers=admin,
        json={"permissions": sorted(set([*emp_orig_perms, "employee.read.all"]))},
    )
    assert grant_resp.status_code == 200

    assert client.get("/api/employees", headers=emp).status_code == 403
    assert client.get("/api/employees?department_id=DEPT_SALES", headers=emp).status_code == 403

    # Admin also blocked by build_scope_filter even if granted employee.read.all
    admin_orig_perms = next(r["permissions"] for r in roles_before if r["role_code"] == "admin")
    assert (
        client.patch(
            "/api/rbac/roles/admin/permissions",
            headers=admin,
            json={"permissions": sorted(set([*admin_orig_perms, "employee.read.all"]))},
        ).status_code
        == 200
    )
    assert client.get("/api/employees", headers=admin).status_code == 403

    # Manager only sees own department and cannot query another department
    mgr_res = client.get("/api/employees", headers=mgr)
    assert mgr_res.status_code == 200
    assert mgr_res.json()["total"] > 0
    assert all(row["department_id"] == "DEPT_SALES" for row in mgr_res.json()["items"])
    assert client.get("/api/employees?department_id=DEPT_TECH", headers=mgr).status_code == 403

    # HR & Executive retain full company directory access
    assert client.get("/api/employees", headers=hr).json()["total"] == 80
    assert client.get("/api/employees", headers=exec_h).json()["total"] == 80


def test_audit_sec02_empty_role_permissions_stay_empty_and_no_stale_user_roles_leak(audit_env):
    client, db_file = audit_env
    admin = _login(client, "admin@company.vn")
    emp = _login(client, "nv007@company.vn")

    # Admin intentionally revokes ALL permissions from employee -> must stay [] (NOT fall back to defaults!)
    revoke_all = client.patch(
        "/api/rbac/roles/employee/permissions",
        headers=admin,
        json={"permissions": []},
    )
    assert revoke_all.status_code == 200, revoke_all.text
    assert revoke_all.json()["permissions"] == []

    me_empty = client.get("/api/auth/me", headers=emp)
    assert me_empty.status_code == 200
    assert me_empty.json()["permissions"] == []
    assert client.get("/api/attendance", headers=emp).status_code == 403

    # Inject a stale HR role mapping into user_roles for NV007 while employees.role stays 'employee'
    conn = get_connection(db_file, readonly=False)
    try:
        emp_uid = conn.execute("SELECT user_id FROM users WHERE LOWER(username) = 'nv007@company.vn'").fetchone()["user_id"]
        hr_rid = conn.execute("SELECT role_id FROM roles WHERE role_code = 'hr'").fetchone()["role_id"]
        conn.execute("INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)", (emp_uid, hr_rid))
        conn.commit()
    finally:
        conn.close()

    # Stale user_roles row MUST NOT leak HR permissions via OR-union!
    me_after_stale = client.get("/api/auth/me", headers=emp).json()
    assert me_after_stale["permissions"] == []
    assert client.get("/api/employees", headers=emp).status_code == 403


def test_audit_sec04_persistent_jwt_revocation_survives_memory_clear(audit_env):
    client, db_file = audit_env
    emp = _login(client, "nv007@company.vn")

    assert client.get("/api/auth/me", headers=emp).status_code == 200
    logout = client.post("/api/auth/logout", headers=emp)
    assert logout.status_code == 200

    # Verify DB persistence in revoked_tokens
    conn = get_connection(db_file, readonly=True)
    try:
        revoked_cnt = conn.execute("SELECT COUNT(*) FROM revoked_tokens").fetchone()[0]
        assert revoked_cnt == 1
    finally:
        conn.close()

    # Simulate backend restart / separate worker by clearing in-memory REVOKED_JTIS
    REVOKED_JTIS.clear()

    # Logged-out JWT MUST STILL be rejected with 401!
    after_restart = client.get("/api/auth/me", headers=emp)
    assert after_restart.status_code == 401


def test_audit_sec06_and_sec07_import_masks_foreign_preview_and_blocks_privileged_overwrite(audit_env):
    client, db_file = audit_env
    hr1 = _login(client, "hr@company.vn")
    hr2 = _login(client, "hr2@company.vn")

    # HR1 uploads employees CSV targeting Admin (NV080) and Executive (NV079)
    csv_priv = (
        "employee_id,full_name,department_id,position,manager_id,start_date,annual_leave_balance,role,email,phone\n"
        "NV080,Fake Admin,DEPT_OPS,Staff,,2023-01-01,12,employee,admin@company.vn,0901000080\n"
        "NV079,Fake Exec,DEPT_OPS,Staff,,2023-01-01,12,employee,director@company.vn,0901000079\n"
    ).encode("utf-8")

    prev = client.post(
        "/api/imports/preview",
        headers=hr1,
        data={"data_type": "employees"},
        files={"file": ("priv_override.csv", io.BytesIO(csv_priv), "text/csv")},
    )
    assert prev.status_code == 200, prev.text
    p = prev.json()
    assert len(p["duplicate_rows"]) == 2
    assert all(d["can_update"] is False for d in p["duplicate_rows"])

    # AUDIT-SEC-06: HR2 must NOT see HR1's unconfirmed preview batch_id in logs list or detail!
    hr2_logs = client.get("/api/imports/logs", headers=hr2).json()["items"]
    matching = next(i for i in hr2_logs if i["id"] == p["log_id"])
    assert matching["batch_id"] is None
    hr2_detail = client.get(f"/api/imports/logs/{p['log_id']}", headers=hr2).json()
    assert hr2_detail["log"]["batch_id"] is None
    assert hr2_detail["preview"]["batch_id"] is None

    # Confirming with duplicate_policy='update' MUST skip Admin & Executive (updated == 0)
    conf = client.post(
        f"/api/imports/confirm/{p['batch_id']}",
        headers=hr1,
        json={"duplicate_policy": "update"},
    )
    assert conf.status_code == 200, conf.text
    assert conf.json()["updated"] == 0
    assert conf.json()["skipped"] == 2

    # Even if a forged staged batch forces can_update=True, server-side transaction MUST raise PermissionError
    conn = get_connection(db_file, readonly=False)
    try:
        staged = stage_and_validate_import(conn, "USR002", "forged.csv", "employees", csv_priv)
        for dup in STAGING_BATCHES[staged["batch_id"]]["duplicate_rows"]:
            dup["can_update"] = True
        with pytest.raises(PermissionError):
            confirm_staged_import(conn, staged["batch_id"], "USR002", duplicate_policy="update")

        roles = {
            r["employee_id"]: r["role"]
            for r in conn.execute("SELECT employee_id, role FROM employees WHERE employee_id IN ('NV079', 'NV080')").fetchall()
        }
        assert roles == {"NV079": "executive", "NV080": "admin"}
    finally:
        conn.close()


def test_audit_biz01_attendance_adjust_validation_and_audit(audit_env):
    client, db_file = audit_env
    hr = _login(client, "hr@company.vn")

    conn = get_connection(db_file, readonly=True)
    rec = conn.execute(
        "SELECT id, work_date FROM attendance WHERE employee_id = 'NV007' AND work_date = '2026-10-02' LIMIT 1"
    ).fetchone()
    conn.close()
    assert rec is not None
    rec_id = rec["id"]

    # Invalid format -> 400
    assert (
        client.patch(
            f"/api/attendance/{rec_id}",
            headers=hr,
            json={"check_in": "invalid-ts", "reason": "Test invalid format"},
        ).status_code
        == 400
    )

    # check_out < check_in -> 400
    assert (
        client.patch(
            f"/api/attendance/{rec_id}",
            headers=hr,
            json={
                "check_in": "2026-10-02 17:00:00",
                "check_out": "2026-10-02 08:00:00",
                "reason": "Test inverted times",
            },
        ).status_code
        == 400
    )

    # Wrong work_date -> 400
    assert (
        client.patch(
            f"/api/attendance/{rec_id}",
            headers=hr,
            json={"check_in": "2026-09-15 08:30:00", "reason": "Wrong date"},
        ).status_code
        == 400
    )

    # absent + non-empty check_in -> 400
    assert (
        client.patch(
            f"/api/attendance/{rec_id}",
            headers=hr,
            json={"status": "absent", "check_in": "2026-10-02 08:30:00", "reason": "Contradictory"},
        ).status_code
        == 400
    )

    # Valid adjustment succeeds & writes audit log
    ok = client.patch(
        f"/api/attendance/{rec_id}",
        headers=hr,
        json={
            "check_in": "2026-10-02 08:25:00",
            "check_out": "2026-10-02 17:35:00",
            "reason": "Điều chỉnh chuẩn sau đối soát vân tay",
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["record"]["source"] == "hr_adjusted"
    assert ok.json()["record"]["check_in"] == "2026-10-02 08:25:00"


def test_audit_biz02_leave_double_review_and_overlap_guard(audit_env):
    client, db_file = audit_env
    emp = _login(client, "nv007@company.vn")
    mgr = _login(client, "manager.sales@company.vn")

    r1 = client.post(
        "/api/leaves",
        headers=emp,
        json={"leave_type": "annual", "from_date": "2026-12-16", "to_date": "2026-12-17", "reason": "Nghỉ việc gia đình"},
    )
    assert r1.status_code == 201
    req_id = r1.json()["request"]["request_id"]

    # Overlapping leave blocked with 409
    overlap = client.post(
        "/api/leaves",
        headers=emp,
        json={"leave_type": "annual", "from_date": "2026-12-17", "to_date": "2026-12-18", "reason": "Trùng ngày"},
    )
    assert overlap.status_code == 409

    # First approval succeeds
    app1 = client.post(
        f"/api/leaves/{req_id}/review",
        headers=mgr,
        json={"decision": "approved", "decision_note": "Duyệt lần 1"},
    )
    assert app1.status_code == 200

    # Second approval attempt strictly rejected (no double approve / no duplicate log)
    app2 = client.post(
        f"/api/leaves/{req_id}/review",
        headers=mgr,
        json={"decision": "approved", "decision_note": "Duyệt trùng"},
    )
    assert app2.status_code == 400

    # Cancel already approved leave strictly rejected
    assert client.post(f"/api/leaves/{req_id}/cancel", headers=emp).status_code == 400

    conn = get_connection(db_file, readonly=True)
    try:
        approve_logs = conn.execute(
            "SELECT COUNT(*) FROM leave_approval_logs WHERE request_id = ? AND action = 'approve'",
            (req_id,),
        ).fetchone()[0]
        assert approve_logs == 1
    finally:
        conn.close()


def test_audit_biz03_ai_daily_no_hallucination_late_count_and_sql_guard_revoked_tokens(audit_env):
    client, db_file = audit_env
    emp = _login(client, "nv007@company.vn")
    mgr = _login(client, "manager.sales@company.vn")

    # SQL Guard MUST block revoked_tokens
    with pytest.raises(SQLGuardError):
        validate_readonly_sql("SELECT * FROM revoked_tokens")

    # Asking "Hôm nay tôi đã chấm công chưa?" when today has no record -> honest insufficient_data (no fake Oct data!)
    today_str = datetime.date.today().isoformat()
    res_empty = client.post("/api/assistant/ask", headers=emp, json={"question": "Hôm nay tôi đã chấm công chưa?"})
    assert res_empty.status_code == 200
    d_empty = res_empty.json()
    assert d_empty["trace"]["tool_name"] == "get_daily_attendance"
    assert d_empty["status"] == "insufficient_data"
    assert today_str in d_empty["answer"]

    # Insert real attendance for NV007 today -> AI reports exact DB check-in/out!
    conn = get_connection(db_file, readonly=False)
    try:
        conn.execute(
            """
            INSERT INTO attendance (employee_id, work_date, check_in, check_out, status, source)
            VALUES ('NV007', ?, ?, NULL, 'present', 'manual')
            """,
            (today_str, f"{today_str} 08:22:00"),
        )
        conn.commit()
        exact_late_sales = conn.execute(
            """
            SELECT COUNT(DISTINCT employee_id)
            FROM v_attendance_daily
            WHERE department_id = 'DEPT_SALES' AND period = '2026-10' AND is_late = 1
            """
        ).fetchone()[0]
    finally:
        conn.close()

    res_today = client.post("/api/assistant/ask", headers=emp, json={"question": "Hôm nay tôi đã chấm công chưa?"})
    assert res_today.status_code == 200
    d_today = res_today.json()
    assert d_today["status"] == "success"
    assert f"{today_str} 08:22:00" in d_today["answer"]

    # Manager asking "Tháng này phòng tôi có bao nhiêu người đi muộn?" returns exact count (not truncated at 5!)
    res_mgr = client.post(
        "/api/assistant/ask",
        headers=mgr,
        json={"question": "Tháng này phòng tôi có bao nhiêu người đi muộn?"},
    )
    assert res_mgr.status_code == 200
    d_mgr = res_mgr.json()
    assert d_mgr["status"] == "success"
    assert d_mgr["trace"]["row_count"] == exact_late_sales
    assert f"Có {exact_late_sales} nhân viên" in d_mgr["answer"]
