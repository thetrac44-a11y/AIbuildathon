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

    # Upload CSV containing: 1 valid new past date, 1 duplicate existing date, 1 invalid unknown emp, 1 formula injection
    csv_payload = (
        "employee_id,work_date,check_in,check_out,status,source\n"
        "NV007,2026-11-07,2026-11-07 08:25:00,2026-11-07 17:35:00,present,import_csv\n"
        "NV007,2026-10-02,2026-10-02 08:20:00,2026-10-02 17:30:00,present,import_csv\n"
        "NV999,2026-11-07,2026-11-07 08:25:00,2026-11-07 17:35:00,present,import_csv\n"
        "NV007,2026-11-14,2026-11-14 08:25:00,2026-11-14 17:35:00,present,=HYPERLINK(\"http://evil\")\n"
    ).encode("utf-8")

    preview = client.post(
        "/api/imports/preview",
        headers=hr_headers,
        data={"data_type": "attendance"},
        files={"file": ("nov_att.csv", io.BytesIO(csv_payload), "text/csv")},
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
            "SELECT COUNT(*) FROM attendance WHERE employee_id = 'NV007' AND work_date = '2026-11-07'"
        ).fetchone()[0]
        assert before_cnt == 0
    finally:
        conn.close()

    # Download errors CSV succeeds and neutralizes formula injection with leading quote
    err_csv = client.get(f"/api/imports/errors/{batch_id}", headers=hr_headers)
    assert err_csv.status_code == 200
    assert "NV999" in err_csv.text
    assert "'=HYPERLINK" in err_csv.text

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
            "NV007,2026-11-14,2026-11-14 08:20:00,2026-11-14 17:30:00,present,import_csv\n"
        ).encode("utf-8")
        rb_preview = stage_and_validate_import(conn, "USR002", "rb.csv", "attendance", csv_rollback)
        with pytest.raises(RuntimeError):
            confirm_staged_import(conn, rb_preview["batch_id"], "USR002", duplicate_policy="skip", force_fail_for_test=True)

        # Row must NOT exist after rollback, and import_logs status must be 'failed'
        after_rb = conn.execute(
            "SELECT COUNT(*) FROM attendance WHERE employee_id = 'NV007' AND work_date = '2026-11-14'"
        ).fetchone()[0]
        assert after_rb == 0
        log_status = conn.execute(
            "SELECT status FROM import_logs WHERE file_name = 'rb.csv' ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        assert log_status == "failed"
    finally:
        conn.close()


def test_import_p1_p2_warnings_future_guard_duplicate_diff_csv_sanitization_and_autoscan(test_env):
    client, db_file = test_env
    hr_headers = _login(client, "hr@company.vn")

    # Seed an approved overtime request for NV011 on Saturday 2026-11-14 to verify OT check suppresses R7 warning
    conn = get_connection(db_file)
    try:
        conn.execute(
            """
            INSERT INTO overtime_requests (employee_id, work_date, status, approved_by)
            VALUES ('NV011', '2026-11-14', 'approved', 'NV001')
            """
        )
        conn.commit()
    finally:
        conn.close()

    # Build CSV covering all P1 + P2 scenarios:
    # - 2 past Saturdays for NV010 with missing check_out (triggers missing_punch + weekend_or_holiday warnings -> R2 & R7 after confirm)
    # - 1 past Saturday for NV010 with full check_in/out (triggers weekend_or_holiday warning)
    # - 1 past Saturday for NV011 WITH approved OT (0 warnings!)
    # - 1 future date for NV010 (2099-11-28, blocked by default unless allow_future_dates=True)
    # - 1 duplicate row for NV007 on 2026-10-02 with DIFFERENT check-in/out times (is_identical=False, existing populated)
    # - 3 error rows: unknown NV999, check_out < check_in, and dangerous formula prefixes (+CMD / -1+cmd / @SUM)
    csv_payload = (
        "employee_id,work_date,check_in,check_out,status,source\n"
        "NV010,2026-11-07,2026-11-07 08:25:00,,present,import_demo\n"
        "NV010,2026-11-14,2026-11-14 08:28:00,,present,import_demo\n"
        "NV010,2026-11-21,2026-11-21 08:30:00,2026-11-21 16:45:00,present,import_demo\n"
        "NV011,2026-11-14,2026-11-14 08:30:00,2026-11-14 12:30:00,present,import_demo\n"
        "NV010,2099-11-28,2099-11-28 08:22:00,2099-11-28 17:10:00,present,import_demo\n"
        "NV007,2026-10-02,2026-10-02 08:00:00,2026-10-02 17:00:00,present,import_demo\n"
        "NV999,2026-11-07,2026-11-07 08:25:00,2026-11-07 17:35:00,present,import_demo\n"
        "NV010,2026-11-08,2026-11-08 17:00:00,2026-11-08 08:00:00,present,import_demo\n"
        "NV010,2026-11-09,2026-11-09 08:25:00,2026-11-09 17:35:00,present,+CMD|' /C calc'!A0\n"
    ).encode("utf-8")

    preview = client.post(
        "/api/imports/preview",
        headers=hr_headers,
        data={"data_type": "attendance"},
        files={"file": ("p1_p2_demo.csv", io.BytesIO(csv_payload), "text/csv")},
    )
    assert preview.status_code == 200, preview.text
    p = preview.json()

    # 5-KPI summary verification
    assert p["summary"]["rows_total"] == 9
    assert p["summary"]["rows_valid"] == 5
    assert p["summary"]["rows_warning"] == 4  # NV010 x4 (NV011 has approved OT -> 0 warnings!)
    assert p["summary"]["rows_future"] == 1
    assert p["summary"]["rows_duplicate"] == 1
    assert p["summary"]["rows_error"] == 3

    # Verify inline warnings per row
    by_emp_date = {(r["employee_id"], r["work_date"]): r for r in p["preview_rows"]}
    w_07 = {w["code"] for w in by_emp_date[("NV010", "2026-11-07")]["warnings"]}
    assert w_07 == {"missing_punch", "weekend_or_holiday"}
    w_21 = {w["code"] for w in by_emp_date[("NV010", "2026-11-21")]["warnings"]}
    assert w_21 == {"weekend_or_holiday"}
    assert by_emp_date[("NV011", "2026-11-14")]["warnings"] == []
    w_future = {w["code"] for w in by_emp_date[("NV010", "2099-11-28")]["warnings"]}
    assert "future_date" in w_future
    assert by_emp_date[("NV010", "2099-11-28")]["is_future_date"] is True

    # Duplicate side-by-side comparison populated
    dup = p["duplicate_rows"][0]
    assert dup["existing"] is not None
    assert dup["existing"]["employee_id"] == "NV007"
    assert dup["is_identical"] is False

    # Structured error fields populated & CSV export neutralizes formula injection
    assert p["error_rows"][0]["fields"]["employee_id"] == "NV999"
    err_csv = client.get(f"/api/imports/errors/{p['batch_id']}", headers=hr_headers)
    assert err_csv.status_code == 200
    assert "'+CMD" in err_csv.text

    # Confirm WITH default allow_future_dates=False -> future row 2099-11-28 is blocked!
    confirm = client.post(
        f"/api/imports/confirm/{p['batch_id']}",
        headers=hr_headers,
        json={"duplicate_policy": "skip"},
    )
    assert confirm.status_code == 200, confirm.text
    c = confirm.json()
    assert c["inserted"] == 4
    assert c["skipped"] == 1
    assert c["rejected_future"] == 1
    assert c["errors"] == 3
    assert c["rejected_total"] == 4
    assert c["allow_future_dates"] is False

    # Verify auto anomaly scan ran on 2026-11 and detected R2 + R7 for NV010!
    assert c["anomaly_scan"] is not None
    assert "2026-11" in c["anomaly_scan"]["periods"]
    assert c["anomaly_scan"]["inserted"] >= 2
    assert c["anomaly_scan"]["by_rule"].get("R2", 0) >= 1
    assert c["anomaly_scan"]["by_rule"].get("R7", 0) >= 1

    # Confirm future row is NOT in DB, while past rows ARE in DB
    conn = get_connection(db_file)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM attendance WHERE employee_id = 'NV010' AND work_date = '2099-11-28'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM attendance WHERE employee_id = 'NV010' AND work_date IN ('2026-11-07','2026-11-14','2026-11-21')"
        ).fetchone()[0] == 3
        nv010_rules = {
            r[0]
            for r in conn.execute(
                "SELECT rule_code FROM anomalies WHERE employee_id = 'NV010' AND period = '2026-11'"
            ).fetchall()
        }
        assert "R2" in nv010_rules
        assert "R7" in nv010_rules
    finally:
        conn.close()

    # Now re-upload ONLY the future row and explicitly confirm with allow_future_dates=True
    future_only = (
        "employee_id,work_date,check_in,check_out,status,source\n"
        "NV010,2099-11-28,2099-11-28 08:22:00,2099-11-28 17:10:00,present,import_sim\n"
    ).encode("utf-8")
    p2 = client.post(
        "/api/imports/preview",
        headers=hr_headers,
        data={"data_type": "attendance"},
        files={"file": ("future_sim.csv", io.BytesIO(future_only), "text/csv")},
    ).json()
    c2 = client.post(
        f"/api/imports/confirm/{p2['batch_id']}",
        headers=hr_headers,
        json={"duplicate_policy": "skip", "allow_future_dates": True},
    )
    assert c2.status_code == 200
    assert c2.json()["inserted"] == 1
    assert c2.json()["rejected_future"] == 0
    assert c2.json()["allow_future_dates"] is True


def test_import_history_detail_persists_across_restart_and_enforces_rbac(test_env):
    client, _ = test_env
    hr1 = _login(client, "hr@company.vn")
    hr2 = _login(client, "hr2@company.vn")
    emp = _login(client, "nv007@company.vn")

    csv_payload = (
        "employee_id,work_date,check_in,check_out,status,source\n"
        "NV010,2026-11-07,2026-11-07 08:25:00,,present,hist_test\n"
        "NV999,2026-11-07,2026-11-07 08:25:00,2026-11-07 17:30:00,present,hist_test\n"
    ).encode("utf-8")

    prev = client.post(
        "/api/imports/preview",
        headers=hr1,
        data={"data_type": "attendance"},
        files={"file": ("hist_replay.csv", io.BytesIO(csv_payload), "text/csv")},
    )
    assert prev.status_code == 200
    p_data = prev.json()
    log_id = p_data["log_id"]
    batch_id = p_data["batch_id"]

    # List logs includes has_snapshot & batch_id
    logs_resp = client.get("/api/imports/logs", headers=hr1)
    assert logs_resp.status_code == 200
    first_log = logs_resp.json()["items"][0]
    assert first_log["id"] == log_id
    assert first_log["batch_id"] == batch_id
    assert first_log["has_snapshot"] is True

    # Non-HR cannot read import log detail (403)
    assert client.get(f"/api/imports/logs/{log_id}", headers=emp).status_code == 403

    # HR2 can inspect audit history detail, but cannot resume-confirm or download HR1's staged errors (SEC-08)
    d_hr2 = client.get(f"/api/imports/logs/{log_id}", headers=hr2)
    assert d_hr2.status_code == 200
    assert d_hr2.json()["has_snapshot"] is True
    assert d_hr2.json()["can_resume_confirm"] is False
    assert d_hr2.json()["can_download_errors"] is False

    # Simulate complete server restart by wiping in-memory STAGING_BATCHES
    STAGING_BATCHES.clear()

    # Owner HR1 can still inspect full snapshot, download errors CSV, AND confirm after restart!
    d_hr1 = client.get(f"/api/imports/logs/{log_id}", headers=hr1)
    assert d_hr1.status_code == 200
    detail = d_hr1.json()
    assert detail["can_resume_confirm"] is True
    assert detail["can_download_errors"] is True
    assert len(detail["preview"]["preview_rows"]) == 1
    assert len(detail["preview"]["error_rows"]) == 1

    err_csv = client.get(f"/api/imports/errors/{batch_id}", headers=hr1)
    assert err_csv.status_code == 200
    assert "NV999" in err_csv.text

    conf = client.post(f"/api/imports/confirm/{batch_id}", headers=hr1, json={"duplicate_policy": "skip"})
    assert conf.status_code == 200
    assert conf.json()["inserted"] == 1

    # After confirmation, history detail reflects completed status + persisted result + anomaly_scan
    d_after = client.get(f"/api/imports/logs/{log_id}", headers=hr1).json()
    assert d_after["log"]["status"] == "completed"
    assert d_after["can_resume_confirm"] is False
    assert d_after["result"]["inserted"] == 1
    assert d_after["result"]["errors"] == 1
    assert d_after["result"]["anomaly_scan"] is not None


def test_import_per_row_duplicate_decisions_audit_log_concurrency_and_rbac(test_env):
    import json

    client, db_file = test_env
    hr1 = _login(client, "hr@company.vn")
    hr2 = _login(client, "hr2@company.vn")
    mgr = _login(client, "manager.sales@company.vn")
    emp = _login(client, "nv007@company.vn")

    # Fetch two real seeded attendance rows for NV007 in 2026-10 to construct:
    # - 1 exact_match duplicate (identical check_in, check_out, status)
    # - 1 key_conflict duplicate we choose to KEEP existing
    # - 1 key_conflict duplicate we choose to UPDATE from Excel
    # - 1 valid new past row (NV010 2026-11-07)
    conn = get_connection(db_file)
    try:
        seeded_rows = conn.execute(
            """
            SELECT employee_id, work_date, check_in, check_out, status
            FROM attendance
            WHERE employee_id = 'NV007' AND work_date LIKE '2026-10-%' AND status = 'present'
            ORDER BY work_date ASC
            LIMIT 3
            """
        ).fetchall()
        assert len(seeded_rows) == 3
        r_exact = dict(seeded_rows[0])
        r_keep = dict(seeded_rows[1])
        r_update = dict(seeded_rows[2])
    finally:
        conn.close()

    csv_payload = (
        "employee_id,work_date,check_in,check_out,status,source\n"
        # Row 2: valid new past attendance record
        "NV010,2026-11-07,2026-11-07 08:25:00,2026-11-07 17:30:00,present,import_per_row\n"
        # Row 3: exact duplicate of r_exact
        f"{r_exact['employee_id']},{r_exact['work_date']},{r_exact['check_in']},{r_exact['check_out']},{r_exact['status']},import_per_row\n"
        # Row 4: key conflict with r_keep (different check_in/out) -> HR will KEEP existing
        f"{r_keep['employee_id']},{r_keep['work_date']},{r_keep['work_date']} 08:05:00,{r_keep['work_date']} 17:05:00,present,import_per_row\n"
        # Row 5: key conflict with r_update (different check_in/out) -> HR will UPDATE from Excel
        f"{r_update['employee_id']},{r_update['work_date']},{r_update['work_date']} 08:12:00,{r_update['work_date']} 17:40:00,present,import_per_row\n"
        # Row 6: invalid row -> must never be imported
        "NV999,2026-11-07,2026-11-07 08:25:00,2026-11-07 17:30:00,present,import_per_row\n"
    ).encode("utf-8")

    prev = client.post(
        "/api/imports/preview",
        headers=hr1,
        data={"data_type": "attendance"},
        files={"file": ("per_row_dup.csv", io.BytesIO(csv_payload), "text/csv")},
    )
    assert prev.status_code == 200, prev.text
    p = prev.json()
    assert p["summary"]["rows_valid"] == 1
    assert p["summary"]["rows_duplicate"] == 3
    assert p["summary"]["rows_error"] == 1

    dups_by_row = {d["row_number"]: d for d in p["duplicate_rows"]}
    assert dups_by_row[3]["match_type"] == "exact_match"
    assert dups_by_row[3]["is_identical"] is True
    assert dups_by_row[3]["comparison_label"] == "Trùng hoàn toàn"
    assert dups_by_row[3]["default_action"] == "keep_existing"

    assert dups_by_row[4]["match_type"] == "key_conflict"
    assert dups_by_row[4]["is_identical"] is False
    assert dups_by_row[4]["comparison_label"] == "Trùng khóa, khác dữ liệu"
    assert "check_in" in dups_by_row[4]["changed_fields"]

    assert dups_by_row[5]["match_type"] == "key_conflict"
    assert dups_by_row[5]["can_update"] is True

    batch_id = p["batch_id"]
    log_id = p["log_id"]

    # RBAC & schema validation checks
    assert client.post(f"/api/imports/confirm/{batch_id}", headers=emp, json={"duplicate_decisions": {"5": "update_from_excel"}}).status_code == 403
    assert client.post(f"/api/imports/confirm/{batch_id}", headers=mgr, json={"duplicate_decisions": {"5": "update_from_excel"}}).status_code == 403
    assert client.post(f"/api/imports/confirm/{batch_id}", headers=hr2, json={"duplicate_decisions": {"5": "update_from_excel"}}).status_code == 403
    assert client.post(f"/api/imports/confirm/{batch_id}", headers=hr1, json={"duplicate_decisions": {"5": "invalid_action"}}).status_code == 422

    # Confirm with per-row choices: row 3 & 4 keep_existing, row 5 update_from_excel
    conf = client.post(
        f"/api/imports/confirm/{batch_id}",
        headers=hr1,
        json={
            "duplicate_policy": "skip",
            "duplicate_decisions": {
                "3": "keep_existing",
                "4": "keep_existing",
                "5": "update_from_excel",
            },
        },
    )
    assert conf.status_code == 200, conf.text
    c = conf.json()
    assert c["inserted"] == 1
    assert c["updated"] == 1
    assert c["skipped"] == 2
    assert c["errors"] == 1
    assert len(c["updated_records"]) == 1
    assert c["updated_records"][0]["employee_id"] == r_update["employee_id"]
    assert c["updated_records"][0]["work_date"] == r_update["work_date"]
    assert c["updated_records"][0]["before"]["check_in"] == r_update["check_in"]
    assert c["updated_records"][0]["after"]["check_in"] == f"{r_update['work_date']} 08:12:00"
    # Auto anomaly scan must cover BOTH 2026-10 (updated row) and 2026-11 (inserted row)!
    assert set(c["anomaly_scan"]["periods"]) == {"2026-10", "2026-11"}

    # Verify DB integrity: no duplicate key created, kept row untouched, updated row updated in-place, before/after logged
    conn = get_connection(db_file)
    try:
        # Row 4 (keep_existing) MUST remain untouched
        keep_live = conn.execute(
            "SELECT check_in, check_out FROM attendance WHERE employee_id = ? AND work_date = ?",
            (r_keep["employee_id"], r_keep["work_date"]),
        ).fetchone()
        assert keep_live["check_in"] == r_keep["check_in"]
        assert keep_live["check_out"] == r_keep["check_out"]

        # Row 5 (update_from_excel) updated in-place with count == 1 (no duplicate key)
        upd_rows = conn.execute(
            "SELECT check_in, check_out, source FROM attendance WHERE employee_id = ? AND work_date = ?",
            (r_update["employee_id"], r_update["work_date"]),
        ).fetchall()
        assert len(upd_rows) == 1
        assert upd_rows[0]["check_in"] == f"{r_update['work_date']} 08:12:00"
        assert upd_rows[0]["check_out"] == f"{r_update['work_date']} 17:40:00"
        assert upd_rows[0]["source"] == "import_per_row"

        # Before/after audit log written in activity_logs
        audit = conn.execute(
            """
            SELECT actor_user_id, action, entity_type, entity_id, before_json, after_json
            FROM activity_logs
            WHERE action = 'import_update_attendance' AND entity_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (f"{r_update['employee_id']}:{r_update['work_date']}",),
        ).fetchone()
        assert audit is not None
        assert audit["actor_user_id"] == "USR002"
        before_obj = json.loads(audit["before_json"])
        after_obj = json.loads(audit["after_json"])
        assert before_obj["check_in"] == r_update["check_in"]
        assert after_obj["check_in"] == f"{r_update['work_date']} 08:12:00"
        assert after_obj["batch_id"] == batch_id
    finally:
        conn.close()

    # History detail preserves duplicate_decisions and updated_records
    hist = client.get(f"/api/imports/logs/{log_id}", headers=hr1).json()
    assert hist["result"]["duplicate_decisions"]["5"] == "update_from_excel"
    assert hist["result"]["duplicate_decisions"]["4"] == "keep_existing"
    assert len(hist["result"]["updated_records"]) == 1

    # --- Concurrency conflict & atomic rollback check ---
    # Stage a batch with 1 new row (NV010 2026-11-14) + 1 duplicate row (r_keep)
    csv_conflict = (
        "employee_id,work_date,check_in,check_out,status,source\n"
        "NV010,2026-11-14,2026-11-14 08:20:00,2026-11-14 17:30:00,present,conflict_test\n"
        f"{r_keep['employee_id']},{r_keep['work_date']},{r_keep['work_date']} 08:01:00,{r_keep['work_date']} 17:01:00,present,conflict_test\n"
    ).encode("utf-8")
    p_conf = client.post(
        "/api/imports/preview",
        headers=hr1,
        data={"data_type": "attendance"},
        files={"file": ("concurrency.csv", io.BytesIO(csv_conflict), "text/csv")},
    ).json()

    # Simulate another process modifying r_keep in DB AFTER preview and BEFORE confirm
    conn = get_connection(db_file)
    try:
        conn.execute(
            "UPDATE attendance SET check_in = ? WHERE employee_id = ? AND work_date = ?",
            (f"{r_keep['work_date']} 09:11:11", r_keep["employee_id"], r_keep["work_date"]),
        )
        conn.commit()
    finally:
        conn.close()

    # Attempting to confirm update on modified row MUST return 409 Conflict AND rollback the entire transaction!
    resp_409 = client.post(
        f"/api/imports/confirm/{p_conf['batch_id']}",
        headers=hr1,
        json={"duplicate_decisions": {"3": "update_from_excel"}},
    )
    assert resp_409.status_code == 409, resp_409.text
    assert "thay đổi" in resp_409.json()["detail"]

    # Verify atomic rollback: neither NV010 2026-11-14 was inserted NOR r_keep's 09:11:11 was overwritten!
    conn = get_connection(db_file)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM attendance WHERE employee_id = 'NV010' AND work_date = '2026-11-14'"
        ).fetchone()[0] == 0
        live_after_409 = conn.execute(
            "SELECT check_in FROM attendance WHERE employee_id = ? AND work_date = ?",
            (r_keep["employee_id"], r_keep["work_date"]),
        ).fetchone()[0]
        assert live_after_409 == f"{r_keep['work_date']} 09:11:11"
        log_row = conn.execute(
            "SELECT status FROM import_logs WHERE id = ?",
            (p_conf["log_id"],),
        ).fetchone()
        assert log_row["status"] == "failed"
    finally:
        conn.close()
