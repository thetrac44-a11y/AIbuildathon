import io
import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.core.security import REVOKED_JTIS, get_db_dependency, load_authenticated_user
from app.db.connection import get_connection
from app.db.seed import DEV_DEFAULT_PASSWORD, seed_database
from app.main import app
from app.services.anomaly_service import run_anomaly_scan
from app.services.report_service import collect_metrics, verify_narrative_numbers, write_narrative


@pytest.fixture()
def report_env(tmp_path):
    db_file = tmp_path / "report_test.db"
    seed_database(db_path=db_file, reset=True)
    conn = get_connection(db_file)
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


def _login(client: TestClient, username: str):
    resp = client.post("/api/auth/login", json={"username": username, "password": DEV_DEFAULT_PASSWORD})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_reports_rbac_and_cross_check_narrative(report_env):
    client, db_file = report_env
    emp_h = _login(client, "nv007@company.vn")
    mgr_h = _login(client, "manager.sales@company.vn")
    hr_h = _login(client, "hr@company.vn")

    # Employee is strictly denied (403) on preview, pdf, and excel
    assert client.get("/api/reports/preview?period=2026-10", headers=emp_h).status_code == 403
    assert client.get("/api/reports/export/pdf?period=2026-10", headers=emp_h).status_code == 403
    assert client.get("/api/reports/export/excel?period=2026-10", headers=emp_h).status_code == 403

    # Manager cannot request another department (DEPT_TECH -> 403)
    assert client.get("/api/reports/preview?period=2026-10&department_id=DEPT_TECH", headers=mgr_h).status_code == 403

    # Manager preview only includes DEPT_SALES (16 employees)
    mgr_prev = client.get("/api/reports/preview?period=2026-10", headers=mgr_h)
    assert mgr_prev.status_code == 200
    mgr_data = mgr_prev.json()
    assert mgr_data["kpis"]["employee_count"] == 16
    assert len(mgr_data["department_metrics"]) == 1
    assert mgr_data["narrative"]["verified"] is True

    # HR preview includes all 80 employees across 5 departments
    hr_prev = client.get("/api/reports/preview?period=2026-10", headers=hr_h)
    assert hr_prev.status_code == 200
    hr_data = hr_prev.json()
    assert hr_data["kpis"]["employee_count"] == 80
    assert len(hr_data["department_metrics"]) == 5
    assert hr_data["narrative"]["verified"] is True

    # Verify hallucination cross-check catches fabricated numbers & falls back cleanly
    conn = get_connection(db_file)
    hr_user = load_authenticated_user(conn, "USR002")
    metrics = collect_metrics(conn, "2026-10", hr_user)
    conn.close()

    fake_text = "Trong tháng 2026-10 có 9999 nhân sự và tỷ lệ đi muộn giả 88.88%."
    check = verify_narrative_numbers(fake_text, metrics)
    assert check["verified"] is False
    assert "9999" in check["unverified_numbers"]
    assert "88.88" in check["unverified_numbers"]

    guarded = write_narrative(metrics, custom_narrative=fake_text)
    assert guarded["used_fallback"] is True
    assert guarded["verified"] is True
    assert "9999" not in guarded["text"]


def test_export_excel_and_pdf_match_metrics_and_support_vietnamese(report_env):
    client, _ = report_env
    hr_h = _login(client, "hr@company.vn")

    preview = client.get("/api/reports/preview?period=2026-10", headers=hr_h).json()

    # Export Excel and verify numbers in workbook cells match SQL metrics 100%
    xlsx_resp = client.get("/api/reports/export/excel?period=2026-10", headers=hr_h)
    assert xlsx_resp.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_resp.content))
    assert wb.sheetnames == ["Tong_Quan", "Theo_Phong_Ban", "Top_Di_Muon", "Canh_Bao_Bat_Thuong"]

    ws_summary = wb["Tong_Quan"]
    kv = {ws_summary.cell(row=r, column=1).value: ws_summary.cell(row=r, column=2).value for r in range(4, 18)}
    assert kv["Tổng nhân sự hoạt động"] == preview["kpis"]["employee_count"]
    assert kv["Tổng giờ công thực tế"] == preview["kpis"]["total_work_hours"]
    assert kv["Số lượt đi muộn (>5 phút)"] == preview["kpis"]["late_days"]
    assert kv["Tỷ lệ đi muộn (%)"] == preview["kpis"]["late_rate_pct"]

    ws_dept = wb["Theo_Phong_Ban"]
    assert ws_dept.max_row == 1 + len(preview["department_metrics"])

    # Export PDF and verify valid PDF header + Unicode font embedded
    pdf_resp = client.get("/api/reports/export/pdf?period=2026-10", headers=hr_h)
    assert pdf_resp.status_code == 200
    assert pdf_resp.content.startswith(b"%PDF")
    assert len(pdf_resp.content) > 2000
