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
def qa_env(tmp_path: Path):
    db_file = tmp_path / "qa_bugfix.db"
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


def test_bug01_bug03_dashboard_anomalies_and_pending_leaves_separation(qa_env):
    client, _ = qa_env
    hr = _login(client, "hr@company.vn")

    dash = client.get("/api/dashboard/summary?period=2026-10", headers=hr).json()
    anom = client.get("/api/anomalies?period=2026-10", headers=hr).json()
    leaves = client.get("/api/leaves?period=2026-10", headers=hr).json()

    # Dashboard open anomalies and Anomalies period=2026-10 open count MUST match identically
    assert dash["kpis"]["open_anomalies"] == anom["summary"]["open"]
    assert dash["kpis"]["high_anomalies"] == anom["summary"]["high"]

    # Pending leaves clearly separated into all active pending vs period-scoped pending
    assert dash["kpis"]["pending_leaves"] == leaves["kpis"]["pending_all"] == 4
    assert dash["kpis"]["pending_leaves_in_period"] == leaves["kpis"]["pending"] == 1


def test_bug02_leaves_period_filtering_and_search_no_ambiguous_sql(qa_env):
    client, _ = qa_env
    hr = _login(client, "hr@company.vn")

    oct_leaves = client.get("/api/leaves?period=2026-10", headers=hr).json()
    all_leaves = client.get("/api/leaves", headers=hr).json()
    assert oct_leaves["period"] == "2026-10"
    assert all(item["period"] == "2026-10" for item in oct_leaves["items"])
    assert oct_leaves["total"] < all_leaves["total"]
    assert oct_leaves["kpis"]["pending"] == 1
    assert oct_leaves["kpis"]["pending_all"] == 4

    # Search parameter must work cleanly with JOIN employees without ambiguous column errors
    search_res = client.get("/api/leaves?search=An", headers=hr)
    assert search_res.status_code == 200
    assert search_res.json()["total"] >= 1


def test_bug04_nv060_triggers_r3_without_false_positive_r6(qa_env):
    _, db_file = qa_env
    conn = get_connection(db_file, readonly=True)
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM v_anomalies").fetchall()]
        nv060_r3 = [r for r in rows if r["employee_id"] == "NV060" and r["rule_code"] == "R3"]
        nv060_r6 = [r for r in rows if r["employee_id"] == "NV060" and r["rule_code"] == "R6"]
        all_r6 = [r for r in rows if r["rule_code"] == "R6"]

        assert len(nv060_r3) == 1
        assert nv060_r3[0]["severity"] == "low"
        assert len(nv060_r6) == 0, f"False positive R6 triggered on NV060: {nv060_r6}"
        # Only S3 (NV023 in Nov 2026) should trigger R6
        assert len(all_r6) == 1
        assert all_r6[0]["employee_id"] == "NV023"
        assert all_r6[0]["period"] == "2026-11"
        assert all_r6[0]["severity"] == "high"
    finally:
        conn.close()


def test_bug05_dashboard_and_reports_metrics_exact_parity(qa_env):
    client, _ = qa_env
    hr = _login(client, "hr@company.vn")
    mgr_sales = _login(client, "manager.sales@company.vn")

    for period in ("2026-10", "2026-09"):
        for headers, dept_qs in [(hr, ""), (hr, "&department_id=DEPT_SALES"), (mgr_sales, "")]:
            dash = client.get(f"/api/dashboard/summary?period={period}{dept_qs}", headers=headers).json()
            rep = client.get(f"/api/reports/preview?period={period}{dept_qs}", headers=headers).json()

            # Overall KPI parity
            assert dash["kpis"]["total_work_hours"] == rep["kpis"]["total_work_hours"]
            assert dash["kpis"]["present_days"] == rep["kpis"]["present_days"]
            assert dash["kpis"]["late_days"] == rep["kpis"]["late_days"]
            assert dash["kpis"]["leave_days"] == rep["kpis"]["leave_days"]
            assert dash["kpis"]["absent_days"] == rep["kpis"]["absent_days"]
            assert dash["kpis"]["late_rate"] == rep["kpis"]["late_rate_pct"]
            assert dash["kpis"]["leave_rate"] == rep["kpis"]["leave_rate_pct"]
            assert dash["kpis"]["open_anomalies"] == rep["kpis"]["open_anomalies"]
            assert dash["kpis"]["high_anomalies"] == rep["kpis"]["high_anomalies"]

            # Per-department metric parity (both 2 decimals & identical leave denominator)
            assert len(dash["department_chart"]) == len(rep["department_metrics"])
            for d_dash, d_rep in zip(dash["department_chart"], rep["department_metrics"]):
                assert d_dash["department_id"] == d_rep["department_id"]
                assert d_dash["late_rate"] == d_rep["late_rate_pct"]
                assert d_dash["leave_rate"] == d_rep["leave_rate_pct"]


def test_bug07_manager_can_review_sync_and_post_blocks_403(qa_env):
    client, db_file = qa_env
    # Promote NV008 in DEPT_SALES to manager so DEPT_SALES has a pending leave submitted by a non-employee role
    conn = get_connection(db_file, readonly=False)
    conn.execute("UPDATE employees SET role = 'manager' WHERE employee_id = 'NV008'")
    cur = conn.execute(
        """
        INSERT INTO leave_requests (employee_id, leave_type, from_date, to_date, reason, status)
        VALUES ('NV008', 'annual', '2026-12-10', '2026-12-11', 'Nghỉ phép cấp quản lý', 'pending')
        """
    )
    mgr_req_id = cur.lastrowid
    conn.commit()
    conn.close()

    mgr_sales = _login(client, "manager.sales@company.vn")
    hr = _login(client, "hr@company.vn")

    # Manager GET /api/leaves: can_review MUST be False for NV008 (manager role), True for NV014 (employee role)
    mgr_items = {i["request_id"]: i for i in client.get("/api/leaves", headers=mgr_sales).json()["items"]}
    assert mgr_items[mgr_req_id]["can_review"] is False
    emp_pending = [i for i in mgr_items.values() if i["employee_id"] == "NV014" and i["status"] == "pending"]
    assert len(emp_pending) == 1 and emp_pending[0]["can_review"] is True

    # Manager POST /api/leaves/{mgr_req_id}/review MUST STILL be blocked with 403
    blocked = client.post(
        f"/api/leaves/{mgr_req_id}/review",
        headers=mgr_sales,
        json={"decision": "approved", "decision_note": "Try approve"},
    )
    assert blocked.status_code == 403

    # HR CAN review manager's leave request
    hr_items = {i["request_id"]: i for i in client.get("/api/leaves", headers=hr).json()["items"]}
    assert hr_items[mgr_req_id]["can_review"] is True


def test_bug09_anomaly_direct_detail_rbac_and_404(qa_env):
    client, db_file = qa_env
    hr = _login(client, "hr@company.vn")
    emp = _login(client, "nv007@company.vn")
    mgr_tech = _login(client, "manager.tech@company.vn")

    conn = get_connection(db_file, readonly=True)
    r5_id = conn.execute("SELECT anomaly_id FROM anomalies WHERE rule_code = 'R5' LIMIT 1").fetchone()["anomaly_id"]
    conn.close()

    assert client.get(f"/api/anomalies/{r5_id}", headers=hr).status_code == 200
    assert client.get(f"/api/anomalies/{r5_id}", headers=emp).status_code == 403
    assert client.get(f"/api/anomalies/{r5_id}", headers=mgr_tech).status_code == 403
    assert client.get("/api/anomalies/999999", headers=hr).status_code == 404


def test_bug10_initial_leave_approval_logs_seeded_idempotently(qa_env):
    client, db_file = qa_env
    hr = _login(client, "hr@company.vn")

    conn = get_connection(db_file, readonly=True)
    total_leaves = conn.execute("SELECT COUNT(*) FROM leave_requests").fetchone()[0]
    approved_or_rejected = conn.execute(
        "SELECT COUNT(*) FROM leave_requests WHERE status IN ('approved', 'rejected')"
    ).fetchone()[0]
    log_count_before = conn.execute("SELECT COUNT(*) FROM leave_approval_logs").fetchone()[0]
    approved_req_id = conn.execute(
        "SELECT request_id FROM leave_requests WHERE status = 'approved' LIMIT 1"
    ).fetchone()["request_id"]
    conn.close()

    # Every seeded leave has a 'submit' log, and every approved/rejected leave also has its review log
    assert log_count_before == total_leaves + approved_or_rejected

    # Re-running seed_database(reset=False) must NOT duplicate approval logs
    seed_database(db_path=db_file, reset=False)
    conn = get_connection(db_file, readonly=True)
    log_count_after = conn.execute("SELECT COUNT(*) FROM leave_approval_logs").fetchone()[0]
    conn.close()
    assert log_count_after == log_count_before

    # Detail API returns full timeline with actor & action
    detail = client.get(f"/api/leaves/{approved_req_id}", headers=hr)
    assert detail.status_code == 200
    timeline = detail.json()["timeline"]
    assert len(timeline) >= 2
    assert timeline[0]["action"] == "submit"
    assert timeline[1]["action"] == "approve"
    assert timeline[1]["actor_name"] is not None


def test_bug11_ai_clarification_for_generic_domain_queries(qa_env):
    client, _ = qa_env
    hr = _login(client, "hr@company.vn")

    for generic_q in ["Chấm công", "Nghỉ phép", "Cảnh báo", "Báo cáo", "chấm công?", "Xem báo cáo"]:
        r = client.post("/api/assistant/ask", headers=hr, json={"question": generic_q})
        assert r.status_code == 200, generic_q
        data = r.json()
        assert data["status"] == "clarification_needed", (generic_q, data)
        assert data.get("clarification_needed") is True
        assert data["trace"]["tool_name"] == "clarification"
        assert data["trace"]["sql_text"] is None
        assert data["trace"]["row_count"] == 0

    # Specific queries must continue to execute SQL normally
    specific = client.post(
        "/api/assistant/ask",
        headers=hr,
        json={"question": "Tổng hợp chấm công toàn công ty tháng 10/2026"},
    ).json()
    assert specific["status"] == "success"
    assert specific["trace"]["tool_name"] == "get_attendance_summary"
    assert specific["trace"]["sql_text"] is not None
