from __future__ import annotations

import datetime
import io
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.security import AuthenticatedUser, assert_department_access, build_scope_filter
from app.schemas.common import RoleEnum
from app.services.import_service import sanitize_cell_for_export
from app.services.metrics_service import compute_attendance_rates

FONT_REGISTERED = False
PDF_FONT_REGULAR = "Helvetica"
PDF_FONT_BOLD = "Helvetica-Bold"


def _ensure_unicode_fonts() -> Tuple[str, str]:
    global FONT_REGISTERED, PDF_FONT_REGULAR, PDF_FONT_BOLD
    if FONT_REGISTERED:
        return PDF_FONT_REGULAR, PDF_FONT_BOLD

    candidates = [
        (Path(r"C:\Windows\Fonts\arial.ttf"), Path(r"C:\Windows\Fonts\arialbd.ttf"), "VN_Arial", "VN_Arial_Bold"),
        (Path(r"C:\Windows\Fonts\tahoma.ttf"), Path(r"C:\Windows\Fonts\tahomabd.ttf"), "VN_Tahoma", "VN_Tahoma_Bold"),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"), "VN_DejaVu", "VN_DejaVu_Bold"),
        (Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"), Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"), "VN_Lib", "VN_Lib_Bold"),
    ]
    for reg_path, bold_path, reg_name, bold_name in candidates:
        if reg_path.exists():
            pdfmetrics.registerFont(TTFont(reg_name, str(reg_path)))
            PDF_FONT_REGULAR = reg_name
            if bold_path.exists():
                pdfmetrics.registerFont(TTFont(bold_name, str(bold_path)))
                PDF_FONT_BOLD = bold_name
            else:
                PDF_FONT_BOLD = reg_name
            FONT_REGISTERED = True
            return PDF_FONT_REGULAR, PDF_FONT_BOLD

    FONT_REGISTERED = True
    return PDF_FONT_REGULAR, PDF_FONT_BOLD


def collect_metrics(
    conn: sqlite3.Connection,
    period: str,
    user: AuthenticatedUser,
    department_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute 100% of report KPIs and tables strictly via SQL from RBAC-validated scope."""
    effective_dept = assert_department_access(user, department_id)
    scope_sql, scope_params = build_scope_filter(user, "employee_id", "department_id")

    where_parts = [scope_sql, "period = ?"]
    params: List[Any] = [*scope_params, period]
    if effective_dept and user.role in (RoleEnum.hr, RoleEnum.executive):
        where_parts.append("department_id = ?")
        params.append(effective_dept)
    where_str = " AND ".join(where_parts)

    scope_label = "Toàn công ty"
    if effective_dept:
        d_row = conn.execute("SELECT name FROM departments WHERE department_id = ?", (effective_dept,)).fetchone()
        scope_label = f"Phòng {d_row['name']}" if d_row else effective_dept

    kpi_row = conn.execute(
        f"""
        SELECT
            COUNT(DISTINCT employee_id) AS employee_count,
            ROUND(COALESCE(SUM(work_hours), 0), 1) AS total_work_hours,
            SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) AS present_days,
            SUM(CASE WHEN is_late = 1 THEN 1 ELSE 0 END) AS late_days,
            SUM(CASE WHEN status = 'on_leave' THEN 1 ELSE 0 END) AS leave_days,
            SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) AS absent_days,
            SUM(CASE WHEN status = 'present' AND (check_in IS NULL OR check_out IS NULL) THEN 1 ELSE 0 END) AS missing_punch_days
        FROM v_attendance_daily
        WHERE {where_str}
        """,
        params,
    ).fetchone()

    present_days = int(kpi_row["present_days"] or 0)
    late_days = int(kpi_row["late_days"] or 0)
    leave_days = int(kpi_row["leave_days"] or 0)
    absent_days = int(kpi_row["absent_days"] or 0)
    missing_days = int(kpi_row["missing_punch_days"] or 0)
    overall_rates = compute_attendance_rates(present_days, late_days, leave_days, absent_days)
    on_time_days = overall_rates["on_time_days"]
    late_rate_pct = overall_rates["late_rate"]
    leave_rate_pct = overall_rates["leave_rate"]

    # Department metrics breakdown
    dept_rows = conn.execute(
        f"""
        SELECT
            department_id,
            department_name,
            COUNT(DISTINCT employee_id) AS employee_count,
            ROUND(COALESCE(SUM(work_hours), 0), 1) AS total_work_hours,
            SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) AS present_days,
            SUM(CASE WHEN is_late = 1 THEN 1 ELSE 0 END) AS late_days,
            SUM(CASE WHEN status = 'on_leave' THEN 1 ELSE 0 END) AS leave_days,
            SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) AS absent_days
        FROM v_attendance_daily
        WHERE {where_str}
        GROUP BY department_id, department_name
        ORDER BY department_name ASC
        """,
        params,
    ).fetchall()

    department_metrics = []
    for r in dept_rows:
        p = int(r["present_days"] or 0)
        l = int(r["late_days"] or 0)
        lv = int(r["leave_days"] or 0)
        ab = int(r["absent_days"] or 0)
        dept_rates = compute_attendance_rates(p, l, lv, ab)
        department_metrics.append(
            {
                "department_id": r["department_id"],
                "department_name": r["department_name"],
                "employee_count": int(r["employee_count"] or 0),
                "total_work_hours": round(float(r["total_work_hours"] or 0.0), 1),
                "present_days": p,
                "late_days": l,
                "late_rate_pct": dept_rates["late_rate"],
                "leave_days": lv,
                "leave_rate_pct": dept_rates["leave_rate"],
                "absent_days": ab,
            }
        )

    # Top 10 late employees in scope
    top_late_rows = conn.execute(
        f"""
        SELECT
            employee_id,
            full_name,
            department_name,
            COUNT(*) AS late_days,
            SUM(late_minutes) AS total_late_minutes,
            ROUND(AVG(late_minutes), 1) AS avg_late_minutes
        FROM v_attendance_daily
        WHERE {where_str} AND is_late = 1
        GROUP BY employee_id, full_name, department_name
        ORDER BY late_days DESC, total_late_minutes DESC
        LIMIT 10
        """,
        params,
    ).fetchall()
    top_late_employees = [dict(r) for r in top_late_rows]

    # Anomalies in scope
    anom_clauses = [scope_sql, "period = ?"]
    anom_params: List[Any] = [*scope_params, period]
    if effective_dept and user.role in (RoleEnum.hr, RoleEnum.executive):
        anom_clauses.append("department_id = ?")
        anom_params.append(effective_dept)
    anom_rows = conn.execute(
        f"""
        SELECT
            anomaly_id, rule_code, anomaly_type, scope_type,
            COALESCE(employee_id, 'Cấp phòng') AS target_code,
            COALESCE(full_name, department_name) AS target_name,
            department_name, severity, review_status, explanation
        FROM v_anomalies
        WHERE {' AND '.join(anom_clauses)}
        ORDER BY CASE severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, anomaly_id DESC
        """,
        anom_params,
    ).fetchall()
    anomalies_list = [dict(r) for r in anom_rows]
    high_anomalies = sum(1 for a in anomalies_list if a["severity"] == "high")
    open_anomalies = sum(1 for a in anomalies_list if a["review_status"] == "open")

    return {
        "period": period,
        "scope_label": scope_label,
        "department_id": effective_dept,
        "generated_by": f"{user.full_name} ({user.employee_id})",
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "kpis": {
            "employee_count": int(kpi_row["employee_count"] or 0),
            "total_work_hours": round(float(kpi_row["total_work_hours"] or 0.0), 1),
            "present_days": present_days,
            "on_time_days": on_time_days,
            "late_days": late_days,
            "late_rate_pct": late_rate_pct,
            "leave_days": leave_days,
            "leave_rate_pct": leave_rate_pct,
            "absent_days": absent_days,
            "missing_punch_days": missing_days,
            "total_anomalies": len(anomalies_list),
            "open_anomalies": open_anomalies,
            "high_anomalies": high_anomalies,
        },
        "department_metrics": department_metrics,
        "top_late_employees": top_late_employees,
        "anomalies": anomalies_list,
    }


def _collect_source_numbers(metrics: Dict[str, Any]) -> Set[str]:
    """Build exact set of numeric string tokens present in source metrics for narrative cross-check."""
    allowed: Set[str] = set()

    def _add_num(v: Any):
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float)):
            allowed.add(str(v))
            if float(v).is_integer():
                allowed.add(str(int(v)))
            else:
                allowed.add(f"{float(v):.1f}".rstrip("0").rstrip("."))
                allowed.add(f"{float(v):.2f}".rstrip("0").rstrip("."))
                allowed.add(f"{float(v):.1f}")
                allowed.add(f"{float(v):.2f}")

    # Allow year and month numbers from period (e.g. '2026-10' -> '2026', '10')
    for part in re.findall(r"\d+", str(metrics.get("period", ""))):
        allowed.add(part)
        allowed.add(str(int(part)))

    for val in metrics.get("kpis", {}).values():
        _add_num(val)
    for dm in metrics.get("department_metrics", []):
        for val in dm.values():
            _add_num(val)
    for tl in metrics.get("top_late_employees", []):
        for val in tl.values():
            _add_num(val)
    return allowed


def verify_narrative_numbers(narrative: str, metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Verify every standalone number in narrative exists in source SQL metrics."""
    allowed = _collect_source_numbers(metrics)
    # Remove employee codes (NV007) and rule codes (R1..R8) before extracting numeric tokens
    cleaned = re.sub(r"\b(?:NV\d+|R[1-8])\b", "", narrative, flags=re.IGNORECASE)
    found_nums = re.findall(r"\d+(?:\.\d+)?", cleaned)
    unverified: List[str] = []
    for num in found_nums:
        normalized = str(int(float(num))) if float(num).is_integer() else num.rstrip("0").rstrip(".")
        if num not in allowed and normalized not in allowed:
            unverified.append(num)
    return {
        "verified": len(unverified) == 0,
        "checked_count": len(found_nums),
        "unverified_numbers": unverified,
    }


def write_narrative(metrics: Dict[str, Any], custom_narrative: Optional[str] = None) -> Dict[str, Any]:
    """Generate concise executive narrative strictly grounded in SQL metrics with fallback & cross-check."""
    k = metrics["kpis"]
    depts = metrics["department_metrics"]
    top_late = metrics["top_late_employees"]

    def _template_narrative() -> str:
        if k["employee_count"] == 0:
            return f"Kỳ {metrics['period']} ({metrics['scope_label']}) hiện chưa có dữ liệu chấm công để tổng hợp."

        parts = [
            f"Trong kỳ {metrics['period']} ({metrics['scope_label']}), hệ thống ghi nhận {k['employee_count']} nhân sự hoạt động "
            f"với tổng cộng {k['total_work_hours']} giờ công thực tế trên {k['present_days']} ngày đi làm.",
            f"Tỷ lệ đi muộn đạt {k['late_rate_pct']}% ({k['late_days']} lượt đi muộn), tỷ lệ nghỉ phép đạt {k['leave_rate_pct']}% "
            f"({k['leave_days']} ngày nghỉ phép), ghi nhận {k['absent_days']} ngày vắng và {k['missing_punch_days']} lượt thiếu chấm công.",
            f"Bộ kiểm toán tự động phát hiện {k['total_anomalies']} cảnh báo bất thường trong kỳ "
            f"(gồm {k['open_anomalies']} cảnh báo đang mở và {k['high_anomalies']} cảnh báo mức cao cần ưu tiên rà soát).",
        ]
        if depts and len(depts) > 1:
            worst = max(depts, key=lambda d: d["late_rate_pct"])
            parts.append(
                f"Xét theo đơn vị, phòng {worst['department_name']} có tỷ lệ đi muộn cao nhất ở mức {worst['late_rate_pct']}% "
                f"({worst['late_days']} lượt)."
            )
        if top_late:
            first = top_late[0]
            parts.append(
                f"Cá nhân có số lượt đi muộn cao nhất trong kỳ là {first['employee_id']} ({first['full_name']}) "
                f"với {first['late_days']} lần đi muộn. Khuyến nghị quản lý trao đổi xác minh nguyên nhân trước khi chốt kỳ."
            )
        return " ".join(parts)

    candidate = custom_narrative if custom_narrative is not None else _template_narrative()
    check = verify_narrative_numbers(candidate, metrics)

    used_fallback = False
    final_text = candidate
    if not check["verified"]:
        # Automatic hallucination guard fallback
        used_fallback = True
        final_text = _template_narrative()
        fallback_check = verify_narrative_numbers(final_text, metrics)
        return {
            "text": final_text,
            "verified": fallback_check["verified"],
            "used_fallback": used_fallback,
            "flagged_unverified_numbers": check["unverified_numbers"],
            "checked_count": fallback_check["checked_count"],
        }

    return {
        "text": final_text,
        "verified": True,
        "used_fallback": used_fallback,
        "flagged_unverified_numbers": [],
        "checked_count": check["checked_count"],
    }


def build_report(
    conn: sqlite3.Connection,
    period: str,
    user: AuthenticatedUser,
    department_id: Optional[str] = None,
) -> Dict[str, Any]:
    metrics = collect_metrics(conn, period=period, user=user, department_id=department_id)
    narrative_info = write_narrative(metrics)
    return {
        **metrics,
        "narrative": narrative_info,
        "definitions": {
            "standard_shift": "08:30–17:30, nghỉ trưa 1 giờ, đủ ngày 8.0 giờ công; ân hạn đi muộn 5 phút.",
            "late_rate_pct": "Số ngày đi muộn (>5 phút) / Tổng số ngày đi làm (present) × 100%.",
            "leave_days": "Tính theo số ngày lịch bao gồm cả ngày đầu và ngày cuối (calendar days inclusive).",
        },
    }


def export_report_excel(report: Dict[str, Any]) -> bytes:
    wb = openpyxl.Workbook()
    header_fill = PatternFill(start_color="102A43", end_color="102A43", fill_type="solid")
    sub_fill = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    title_font = Font(name="Calibri", size=13, bold=True, color="FFFFFF")
    body_font = Font(name="Calibri", size=11)
    thin = Side(border_style="thin", color="CBD5E1")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    def _style_table(ws, start_row: int, headers: List[str], rows: List[List[Any]], widths: List[int]):
        for col_idx, h in enumerate(headers, start=1):
            c = ws.cell(row=start_row, column=col_idx, value=h)
            c.fill = sub_fill
            c.font = header_font
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = border
        for r_offset, row_vals in enumerate(rows, start=1):
            for col_idx, val in enumerate(row_vals, start=1):
                c = ws.cell(row=start_row + r_offset, column=col_idx, value=sanitize_cell_for_export(val))
                c.font = body_font
                c.border = border
                c.alignment = Alignment(vertical="center", wrap_text=True)
        for col_idx, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(col_idx)].width = w

    # Sheet 1: Tong_Quan
    ws1 = wb.active
    ws1.title = "Tong_Quan"
    ws1.merge_cells("A1:C1")
    ws1["A1"] = f"BÁO CÁO CHẤM CÔNG & NHÂN SỰ KỲ {report['period']} ({report['scope_label']})"
    ws1["A1"].font = title_font
    ws1["A1"].fill = header_fill
    ws1["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws1.row_dimensions[1].height = 30

    k = report["kpis"]
    summary_rows = [
        ["Kỳ báo cáo", report["period"], ""],
        ["Phạm vi dữ liệu", report["scope_label"], ""],
        ["Người tạo báo cáo", report["generated_by"], ""],
        ["Thời điểm tạo", report["generated_at"], ""],
        ["Tổng nhân sự hoạt động", k["employee_count"], "người"],
        ["Tổng giờ công thực tế", k["total_work_hours"], "giờ"],
        ["Số ngày đi làm (present)", k["present_days"], "ngày"],
        ["Số lượt đi muộn (>5 phút)", k["late_days"], "lượt"],
        ["Tỷ lệ đi muộn (%)", k["late_rate_pct"], "%"],
        ["Số ngày nghỉ phép", k["leave_days"], "ngày"],
        ["Tỷ lệ nghỉ phép (%)", k["leave_rate_pct"], "%"],
        ["Số ngày vắng", k["absent_days"], "ngày"],
        ["Số lượt thiếu chấm công", k["missing_punch_days"], "lượt"],
        ["Tổng cảnh báo bất thường", k["total_anomalies"], f"({k['high_anomalies']} mức cao)"],
    ]
    _style_table(ws1, 3, ["Chỉ tiêu", "Giá trị", "Đơn vị / Ghi chú"], summary_rows, [32, 24, 34])

    nar_row = 3 + len(summary_rows) + 2
    ws1.cell(row=nar_row, column=1, value="Nhận xét tổng quan (Đã kiểm chứng số liệu):").font = Font(bold=True)
    ws1.merge_cells(start_row=nar_row + 1, start_column=1, end_row=nar_row + 2, end_column=3)
    nar_cell = ws1.cell(row=nar_row + 1, column=1, value=sanitize_cell_for_export(report["narrative"]["text"]))
    nar_cell.alignment = Alignment(wrap_text=True, vertical="top")

    # Sheet 2: Theo_Phong_Ban
    ws2 = wb.create_sheet("Theo_Phong_Ban")
    dept_rows = [
        [
            d["department_id"], d["department_name"], d["employee_count"], d["total_work_hours"],
            d["present_days"], d["late_days"], d["late_rate_pct"], d["leave_days"], d["absent_days"],
        ]
        for d in report["department_metrics"]
    ]
    _style_table(
        ws2,
        1,
        ["Mã phòng", "Tên phòng ban", "Nhân sự", "Tổng giờ công", "Ngày đi làm", "Lượt đi muộn", "Tỷ lệ muộn (%)", "Ngày nghỉ phép", "Ngày vắng"],
        dept_rows,
        [14, 22, 12, 16, 14, 14, 15, 15, 12],
    )

    # Sheet 3: Top_Di_Muon
    ws3 = wb.create_sheet("Top_Di_Muon")
    late_rows = [
        [t["employee_id"], t["full_name"], t["department_name"], t["late_days"], t["total_late_minutes"], t["avg_late_minutes"]]
        for t in report["top_late_employees"]
    ]
    _style_table(
        ws3,
        1,
        ["Mã NV", "Họ và tên", "Phòng ban", "Số lần đi muộn", "Tổng phút muộn", "Trung bình (phút)"],
        late_rows,
        [12, 26, 20, 16, 16, 18],
    )

    # Sheet 4: Canh_Bao_Bat_Thuong
    ws4 = wb.create_sheet("Canh_Bao_Bat_Thuong")
    anom_rows = [
        [a["rule_code"], a["anomaly_type"], a["target_code"], a["target_name"], a["department_name"], a["severity"], a["review_status"], a["explanation"]]
        for a in report["anomalies"]
    ]
    _style_table(
        ws4,
        1,
        ["Mã QT", "Loại bất thường", "Đối tượng", "Tên đối tượng", "Phòng ban", "Mức độ", "Trạng thái", "Giải thích trung tính"],
        anom_rows,
        [10, 20, 14, 24, 18, 12, 14, 58],
    )

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_report_pdf(report: Dict[str, Any]) -> bytes:
    reg_font, bold_font = _ensure_unicode_fonts()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "VNTitle",
        parent=styles["Heading1"],
        fontName=bold_font,
        fontSize=15,
        textColor=colors.HexColor("#102A43"),
        spaceAfter=6,
    )
    h2_style = ParagraphStyle(
        "VNH2",
        parent=styles["Heading2"],
        fontName=bold_font,
        fontSize=11,
        textColor=colors.HexColor("#2563EB"),
        spaceBefore=10,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "VNBody",
        parent=styles["Normal"],
        fontName=reg_font,
        fontSize=9.5,
        leading=14,
        textColor=colors.HexColor("#1E293B"),
    )
    small_style = ParagraphStyle(
        "VNSmall",
        parent=body_style,
        fontSize=8.5,
        textColor=colors.HexColor("#475569"),
    )

    elements = []
    elements.append(Paragraph(f"BÁO CÁO CHẤM CÔNG & NHÂN SỰ ĐỊNH KỲ – {report['period']}", title_style))
    elements.append(
        Paragraph(
            f"Phạm vi: <b>{report['scope_label']}</b> | Người tạo: {report['generated_by']} | Thời điểm: {report['generated_at']}",
            small_style,
        )
    )
    elements.append(Spacer(1, 6))

    # KPI Summary Table
    k = report["kpis"]
    elements.append(Paragraph("1. Chỉ số tổng quan (KPIs)", h2_style))
    kpi_data = [
        ["Chỉ số", "Giá trị", "Chỉ số", "Giá trị"],
        ["Nhân sự hoạt động", f"{k['employee_count']} người", "Tổng giờ công", f"{k['total_work_hours']} giờ"],
        ["Ngày đi làm (present)", f"{k['present_days']} ngày", "Tỷ lệ đi muộn", f"{k['late_rate_pct']}% ({k['late_days']} lượt)"],
        ["Ngày nghỉ phép", f"{k['leave_days']} ngày ({k['leave_rate_pct']}%)", "Ngày vắng / Thiếu chấm", f"{k['absent_days']} vắng / {k['missing_punch_days']} thiếu"],
        ["Cảnh báo bất thường", f"{k['total_anomalies']} ({k['open_anomalies']} mở)", "Cảnh báo mức cao", f"{k['high_anomalies']} cảnh báo"],
    ]
    t_kpi = Table(kpi_data, colWidths=[45 * mm, 42 * mm, 45 * mm, 44 * mm])
    t_kpi.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#102A43")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), bold_font),
                ("FONTNAME", (0, 1), (-1, -1), reg_font),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                ("PADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    elements.append(t_kpi)

    # Narrative section
    elements.append(Paragraph("2. Nhận xét điều hành (Đã đối chiếu số liệu gốc)", h2_style))
    status_badge = "ĐÃ KIỂM CHỨNG 100%" if report["narrative"]["verified"] else "CẦN RÀ SOÁT"
    elements.append(Paragraph(f"<i>Trạng thái kiểm chứng số liệu: {status_badge}</i>", small_style))
    elements.append(Spacer(1, 3))
    elements.append(Paragraph(report["narrative"]["text"], body_style))

    # Department breakdown table
    if report["department_metrics"]:
        elements.append(Paragraph("3. Thống kê theo phòng ban", h2_style))
        dept_table_data = [["Phòng ban", "Nhân sự", "Giờ công", "Đi làm", "Đi muộn", "Tỷ lệ muộn", "Nghỉ phép"]]
        for d in report["department_metrics"]:
            dept_table_data.append(
                [
                    d["department_name"],
                    str(d["employee_count"]),
                    str(d["total_work_hours"]),
                    str(d["present_days"]),
                    str(d["late_days"]),
                    f"{d['late_rate_pct']}%",
                    str(d["leave_days"]),
                ]
            )
        t_dept = Table(dept_table_data, colWidths=[40 * mm, 18 * mm, 24 * mm, 22 * mm, 22 * mm, 26 * mm, 24 * mm])
        t_dept.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563EB")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), bold_font),
                    ("FONTNAME", (0, 1), (-1, -1), reg_font),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.2),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                    ("PADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        elements.append(t_dept)

    # Anomalies list
    if report["anomalies"]:
        elements.append(Paragraph("4. Cảnh báo bất thường nổi bật trong kỳ", h2_style))
        anom_table_data = [["Mã", "Đối tượng", "Phòng ban", "Mức độ", "Mô tả trung tính"]]
        for a in report["anomalies"][:10]:
            anom_table_data.append(
                [
                    a["rule_code"],
                    f"{a['target_code']} - {a['target_name']}",
                    a["department_name"] or "",
                    a["severity"].upper(),
                    Paragraph(a["explanation"], small_style),
                ]
            )
        t_anom = Table(anom_table_data, colWidths=[12 * mm, 36 * mm, 26 * mm, 18 * mm, 84 * mm])
        t_anom.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#102A43")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), bold_font),
                    ("FONTNAME", (0, 1), (-1, -1), reg_font),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("PADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        elements.append(t_anom)

    elements.append(Spacer(1, 8))
    elements.append(
        Paragraph(
            f"Ghi chú nghiệp vụ: {report['definitions']['standard_shift']} {report['definitions']['leave_days']}",
            small_style,
        )
    )

    doc.build(elements)
    return buf.getvalue()
