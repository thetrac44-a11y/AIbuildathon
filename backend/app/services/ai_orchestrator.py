from __future__ import annotations

import datetime
import re
from typing import Any, Dict, List, Optional, Tuple

from app.core.security import AuthenticatedUser, resolve_ai_effective_scope
from app.schemas.common import RoleEnum
from app.services.ai_citation_service import build_sql_citation, format_rag_citations_markdown
from app.services.ai_context_manager import (
    build_updated_context_state,
    get_or_create_conversation,
    resolve_followup_entities,
    save_conversation_turn,
)
from app.services.ai_entities import (
    extract_departments,
    extract_employee_codes,
    extract_periods_info,
    get_available_periods,
    get_latest_attendance_period,
    is_explicit_self_query,
    resolve_employee_name_in_scope,
)
from app.services.ai_fact_verifier import verify_response_facts
from app.services.ai_llm_client import BaseLLMProvider, synthesize_with_gemini
from app.services.ai_rag_service import query_rag_knowledge
from app.services.ai_router import RoutingPlan, SubQuery, _extract_leave_status, _extract_severity, route_query
from app.services.ai_tools import (
    compare_department_metrics,
    compare_departments_full,
    compare_periods,
    get_anomalies_by_department,
    get_attendance_summary,
    get_attendance_trend,
    get_daily_attendance,
    get_employee_attendance_detail,
    get_employee_directory_summary,
    get_leave_balance,
    get_leave_by_department,
    get_top_late_employees,
    list_anomalies_tool,
    list_holidays_and_overtime,
    list_leave_requests_detail,
    resolve_employee_in_scope,
)

# =============================================================================
# SECURITY & POLICY GUARDS (AUTHORITATIVE — NEVER DELEGATED TO LLM)
# =============================================================================

PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(?:previous|prior|above)",
    r"disregard\s+(all\s+)?(?:previous|prior|system)",
    r"bỏ\s*qua\s+(?:mọi\s+|tất\s+cả\s+)?(?:hướng\s*dẫn|quy\s*tắc|chỉ\s*thị)",
    r"quên\s+(?:hết\s+|mọi\s+)?(?:hướng\s*dẫn|quy\s*tắc)",
    r"đổi\s+quyền",
    r"nâng\s+quyền",
    r"set\s+role",
    r"drop\s+table",
    r"delete\s+from",
    r"update\s+employees",
    r"password_hash",
    r"(?:in|xuất|xem|lấy|dump|select|show|liệt\s*kê|trích|đọc|tiết\s*lộ|reveal)\b.{0,35}\b(?:mật\s*khẩu|password|api[_\s]?key|jwt_secret)\b",
    r"\b(?:mật\s*khẩu|password)\s+(?:của|người|admin|hr|giám\s*đốc|trưởng\s*phòng|nhân\s*viên|tài\s*khoản\s+khác)\b",
    r"\bbảng\s+users\b",
    r"system\s*prompt",
    r"bypass\s+rbac",
    r"vượt\s+qua\s+rbac",
    r"show\s+all\s+tables",
    r"sqlite_master",
    r"pg_catalog",
    r"information_schema",
    r"execute\s+sql\b",
]

OUT_OF_SCOPE_PATTERNS = [
    r"\blương\b",
    r"tiền\s*lương",
    r"bảng\s*lương",
    r"mức\s*lương",
    r"thu\s*nhập",
    r"thuế\s*tncn",
    r"bảo\s*hiểm\s*xã\s*hội",
    r"\bpayslip\b",
    r"\bpayroll\b",
    r"tuyển\s*dụng",
    r"lọc\s*cv",
]

WRITE_ACTION_PATTERNS = [
    r"(?:hãy\s+|nhờ\s+|vui\s+lòng\s+)?(?:tạo|đăng\s*ký|gửi)\s+(?:giúp\s+(?:tôi\s+)?)?(?:một\s+)?đơn\s+(?:xin\s+)?(?:nghỉ\s*phép|phép|tăng\s*ca)",
    r"(?:hãy\s+|nhờ\s+)?(?:phê\s*duyệt|duyệt|từ\s*chối|hủy)\s+(?:ngay\s+|giúp\s+(?:tôi\s+)?)?đơn\b",
    r"(?:hãy\s+|nhờ\s+)?(?:sửa|điều\s*chỉnh|chỉnh\s*sửa|cập\s*nhật|xóa)\s+(?:giúp\s+(?:tôi\s+)?)?(?:giờ\s+)?(?:chấm\s*công|giờ\s+vào|giờ\s+ra|nhân\s*viên|tài\s*khoản|cảnh\s*báo)",
    r"(?:hãy\s+|nhờ\s+)?(?:thêm\s+mới|tạo\s+mới|khóa)\s+(?:giúp\s+(?:tôi\s+)?)?(?:nhân\s*viên|tài\s*khoản)",
]

POLICY_INQUIRY_EXEMPT_PATTERN = re.compile(
    r"\b(?:quy\s*trình|thủ\s*tục|quy\s*định|quy\s*chế|nội\s*quy|điều\s*kiện|hướng\s*dẫn|chính\s*sách|thực\s*hiện\s+như\s+thế\s+nào|làm\s+sao\s+để)\b",
    flags=re.IGNORECASE,
)
EXPLICIT_IMPERATIVE_WRITE_PATTERN = re.compile(
    r"\b(?:hãy|nhờ|vui\s+lòng)\s+(?:tạo|đăng\s*ký|gửi|phê\s*duyệt|duyệt|từ\s*chối|hủy|sửa|điều\s*chỉnh|cập\s*nhật|xóa|khóa)\b"
    r"|\b(?:phê\s*duyệt|duyệt|từ\s*chối|hủy|xóa)\s+(?:ngay|giúp\s+tôi)\b"
    r"|\b(?:tạo|gửi)\s+giúp\s+tôi\b",
    flags=re.IGNORECASE,
)

ACCUSATORY_PATTERNS = [
    r"kết\s+luận\s+(?:nhân\s+viên\s+)?(?:gian\s+lận|vi\s+phạm\s+kỷ\s+luật)",
    r"chắc\s+chắn\s+(?:đã\s+)?gian\s+lận",
]

LEAVE_TYPE_LABELS = {
    "annual": "Phép năm",
    "sick": "Nghỉ ốm",
    "personal": "Việc riêng",
    "unpaid": "Không lương",
}

LEAVE_STATUS_LABELS = {
    "pending": "Chờ duyệt",
    "approved": "Đã duyệt",
    "rejected": "Từ chối",
    "cancelled": "Đã hủy",
}

COLUMN_LABELS_VI: Dict[str, str] = {
    "employee_id": "Mã NV",
    "full_name": "Họ và tên",
    "department_id": "Mã phòng",
    "department_name": "Phòng ban",
    "position": "Chức danh",
    "manager_id": "Mã quản lý",
    "manager_name": "Quản lý trực tiếp",
    "start_date": "Ngày vào làm",
    "role": "Vai trò",
    "period": "Kỳ",
    "work_date": "Ngày công",
    "check_in": "Giờ vào",
    "check_out": "Giờ ra",
    "status": "Trạng thái",
    "late_minutes": "Phút muộn",
    "work_hours": "Giờ công",
    "employee_count": "Số nhân sự",
    "total_work_hours": "Tổng giờ công",
    "present_days": "Ngày đi làm",
    "on_time_days": "Ngày đúng giờ",
    "on_time_rate_pct": "Tỷ lệ đúng giờ (%)",
    "late_days": "Số lần đi muộn",
    "late_rate_pct": "Tỷ lệ đi muộn (%)",
    "total_late_minutes": "Tổng phút muộn",
    "avg_late_minutes": "TB phút muộn",
    "leave_days": "Ngày nghỉ phép",
    "leave_rate_pct": "Tỷ lệ nghỉ phép (%)",
    "absent_days": "Ngày vắng",
    "missing_punch_days": "Thiếu chấm công",
    "annual_leave_balance": "Quỹ phép năm",
    "used_annual_days": "Đã duyệt",
    "remaining_annual_days": "Còn lại",
    "request_id": "Mã đơn",
    "leave_type": "Loại phép",
    "from_date": "Từ ngày",
    "to_date": "Đến ngày",
    "reason": "Lý do",
    "decision_note": "Ghi chú duyệt",
    "requires_executive_approval": "Duyệt cấp cao",
    "total_requests": "Tổng số đơn",
    "approved_requests": "Đã duyệt",
    "pending_requests": "Chờ duyệt",
    "rejected_requests": "Từ chối",
    "approved_leave_days": "Ngày phép đã duyệt",
    "anomaly_id": "Mã CB",
    "rule_code": "Quy tắc",
    "anomaly_type": "Loại cảnh báo",
    "scope_type": "Phạm vi",
    "target_code": "Đối tượng",
    "target_name": "Tên đối tượng",
    "severity": "Mức độ",
    "review_status": "Trạng thái xử lý",
    "explanation": "Giải thích trung tính",
    "total_anomalies": "Tổng cảnh báo",
    "open_anomalies": "Đang mở",
    "high_anomalies": "Mức cao",
    "medium_anomalies": "Mức trung bình",
    "low_anomalies": "Mức thấp",
    "rule_breakdown": "Phân rã R1-R8",
    "approved_by": "Người duyệt",
}

TOOL_SOURCE_LABELS_VI: Dict[str, str] = {
    "get_daily_attendance": "Dữ liệu chấm công theo ngày",
    "get_attendance_summary": "Tổng hợp chấm công theo kỳ",
    "get_top_late_employees": "Thống kê lượt đi muộn",
    "get_employee_attendance_detail": "Chi tiết ngày chấm công",
    "get_leave_balance": "Quỹ phép năm nhân viên",
    "list_leave_requests_detail": "Danh sách đơn nghỉ phép",
    "get_leave_by_department": "Thống kê nghỉ phép theo phòng ban",
    "list_anomalies": "Cảnh báo kiểm toán R1-R8",
    "get_anomalies_by_department": "Phân bổ cảnh báo R1-R8 theo phòng ban",
    "compare_department_metrics": "So sánh chuyên cần phòng ban",
    "compare_departments_full": "So sánh đa chỉ số phòng ban & R1-R8",
    "compare_periods": "So sánh chấm công giữa hai kỳ",
    "get_attendance_trend": "Xu hướng chấm công nhiều tháng",
    "get_employee_directory_summary": "Danh bạ nhân sự & Trưởng phòng",
    "list_holidays_and_overtime": "Ngày lễ & Đơn làm thêm giờ (OT)",
}

ROLE_LABELS_VI: Dict[RoleEnum, str] = {
    RoleEnum.employee: "Nhân viên",
    RoleEnum.manager: "Trưởng phòng",
    RoleEnum.hr: "Nhân sự (HR)",
    RoleEnum.executive: "Ban Điều hành",
    RoleEnum.admin: "Quản trị hệ thống",
}


def get_suggested_prompts(role: RoleEnum) -> List[str]:
    if role == RoleEnum.employee:
        return [
            "Tháng 10/2026 tôi đi muộn bao nhiêu lần và cụ thể vào những ngày nào?",
            "Tôi còn bao nhiêu ngày phép năm và có đơn nghỉ phép nào đang chờ duyệt không?",
            "Theo quy định công ty, đi muộn quá bao nhiêu phút thì bị tính trễ giờ?",
            "Tháng 10/2026 tôi đi muộn mấy lần và theo quy chế công ty, mức này có chạm ngưỡng cảnh báo R1 không?",
        ]
    if role == RoleEnum.manager:
        return [
            "Tổng hợp chấm công phòng tôi tháng 10/2026",
            "Phòng tôi hiện có những đơn nghỉ phép nào đang chờ duyệt?",
            "So sánh tình hình đi muộn của phòng tôi giữa tháng 09/2026 và tháng 10/2026",
            "Phòng Kinh doanh có cảnh báo R5 nào trong tháng 10/2026 và quy trình xử lý cảnh báo R5 quy định thế nào?",
        ]
    if role == RoleEnum.executive:
        return [
            "So sánh toàn diện 5 phòng ban trong tháng 10/2026 về tỷ lệ đúng giờ, đi muộn, nghỉ phép và số cảnh báo R1-R8",
            "Xu hướng tỷ lệ đi muộn toàn công ty trong 6 tháng (06/2026–11/2026) biến động ra sao?",
            "Hiện có những đơn nghỉ phép đặc biệt nào đang chờ Ban Điều hành phê duyệt?",
            "Tóm tắt rủi ro chấm công nổi bật nhất kỳ gần nhất toàn công ty và đề xuất hướng xử lý theo cẩm nang kiểm soát R1-R8",
        ]
    if role == RoleEnum.admin:
        return []
    return [
        "Phòng nào có tỷ lệ đi muộn cao nhất tháng 10/2026?",
        "Ai đang vượt quỹ phép năm (R8) và nội quy công ty quy định cách tính số ngày phép năm ra sao?",
        "Cảnh báo R7 chấm công cuối tuần tháng 10/2026 gồm những ai, họ đã có đơn tăng ca được duyệt chưa và chính sách làm thêm cuối tuần quy định gì?",
        "Phòng Kỹ thuật hiện có bao nhiêu nhân sự và ai là Trưởng phòng?",
    ]


def _extract_rule_codes(question: str) -> List[str]:
    # Strip full range expressions like "R1-R8" or "R1–R8" so they mean ALL rules rather than filtering to R1 only!
    cleaned = re.sub(r"\bR[1-8]\s*[-–—~]\s*R[1-8]\b", " ", question, flags=re.IGNORECASE)
    found: List[str] = []
    for m in re.findall(r"\b(R[1-8])\b", cleaned, flags=re.IGNORECASE):
        u = m.upper()
        if u not in found:
            found.append(u)
    return found


def _scope_audit_label(user: AuthenticatedUser, effective_scope: str) -> str:
    if user.role == RoleEnum.admin or effective_scope == "none":
        return "system" if user.role == RoleEnum.admin else "none"
    return effective_scope


def _scope_human_label(user: AuthenticatedUser, effective_scope: str, force_self: bool = False) -> str:
    if force_self or effective_scope == "self":
        return f"Cá nhân ({user.employee_id})"
    if effective_scope == "department":
        return f"Phòng {user.department_name}"
    if effective_scope == "all":
        return "Toàn công ty"
    return "Không được cấp quyền"


def _log_audit(
    conn: Any,
    user: AuthenticatedUser,
    question: str,
    tool_name: Optional[str],
    sql_text: Optional[str],
    row_count: int,
    status: str,
    query_type: Optional[str] = None,
    effective_scope: Optional[str] = None,
) -> None:
    db_status = status if status in ("success", "blocked", "error", "insufficient_data") else "success"
    eff = effective_scope if effective_scope is not None else resolve_ai_effective_scope(user)
    scope = _scope_audit_label(user, eff)
    success_flag = 1 if db_status == "success" else 0
    resolved_qtype = query_type or (
        "rbac_block"
        if db_status == "blocked"
        else ("ai_strategy" if user.role == RoleEnum.executive else "ai_sql")
    )
    conn.execute(
        """
        INSERT INTO query_audit_log (
            user_id, role, question, query_type, tool_name, sql_text, scope, row_count, success, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user.user_id,
            user.role.value,
            question[:1000],
            resolved_qtype,
            tool_name,
            sql_text,
            scope,
            row_count,
            success_flag,
            db_status,
        ),
    )
    conn.commit()


def _column_labels_for(columns: List[str]) -> Dict[str, str]:
    return {col: COLUMN_LABELS_VI.get(col, col) for col in columns}


def _suggested_actions_for(q_lower: str, route_type: str, sql_intents: List[str]) -> List[Dict[str, str]]:
    actions: List[Dict[str, str]] = []

    def _add(label: str, path: str) -> None:
        if all(a["path"] != path for a in actions):
            actions.append({"label": label, "path": path})

    if any(k in q_lower for k in ["đổi mật khẩu", "mật khẩu", "/profile"]):
        _add("Mở Hồ sơ cá nhân", "/profile")
    if any(k in q_lower for k in ["đơn nghỉ", "nghỉ phép", "chờ duyệt", "hủy đơn", "phê duyệt"]) or any(
        i in ("leave_requests_detail", "leave_balance", "leave_by_department") for i in sql_intents
    ):
        _add("Mở Đơn nghỉ phép", "/leaves")
    if any(k in q_lower for k in ["cảnh báo", "r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8"]) or any(
        i in ("anomalies_list", "anomalies_by_department", "notable_anomalies") for i in sql_intents
    ):
        _add("Mở Cảnh báo bất thường", "/anomalies")
    if "hôm nay" in q_lower and "chấm công" in q_lower:
        _add("Mở Chấm công", "/attendance")
    return actions[:3]


def _execute_sql_subquery(
    conn: Any,
    user: AuthenticatedUser,
    sq: SubQuery,
    entities: Dict[str, Any],
    effective_scope: str,
    prior_sql_evidences: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Execute a single SQL sub-query strictly via RBAC-scoped parameterized tools in ai_tools.py."""
    intent = sq.intent
    params = dict(sq.params or {})

    mentioned_depts: List[str] = entities.get("mentioned_depts") or []
    mentioned_dept: Optional[str] = params.get("department_name") or (mentioned_depts[0] if mentioned_depts else None)
    target_emp: Optional[str] = params.get("target_emp") or entities.get("target_emp")
    force_self: bool = bool(params.get("force_self") if "force_self" in params else entities.get("force_self"))
    period_info: Dict[str, Any] = entities.get("period_info") or {}
    period: Optional[str] = params.get("period") if "period" in params else period_info.get("primary")
    explicit_periods: List[str] = period_info.get("periods") or []
    query_periods: Optional[List[str]] = (
        params.get("periods")
        if "periods" in params
        else (explicit_periods if (period_info.get("is_range") or period_info.get("is_quarter")) else None)
    )
    latest_period: str = entities.get("latest_period") or get_latest_attendance_period(conn)
    effective_period: str = period or latest_period
    period_label = period_info.get("quarter_label") or effective_period
    scope_human = _scope_human_label(user, effective_scope, force_self=force_self)

    def _pack(
        status: str,
        text: str,
        res: Dict[str, Any],
        chart: Optional[Dict[str, Any]] = None,
        derived_facts: Optional[Dict[str, Any]] = None,
        used_period: Optional[str] = None,
    ) -> Dict[str, Any]:
        tool_name = str(res.get("tool_name") or intent)
        rows = res.get("rows") or []
        citation = build_sql_citation(
            source_label=TOOL_SOURCE_LABELS_VI.get(tool_name, tool_name),
            scope_label=scope_human,
            tool_name=tool_name,
            record_count=len(rows),
            period=used_period,
            verified=True,
        )
        return {
            "intent": intent,
            "status": status,
            "text": text,
            "tool_name": tool_name,
            "sql_text": res.get("sql_text"),
            "rows": rows,
            "row_count": len(rows),
            "execution_ms": float(res.get("execution_ms") or 0.0),
            "chart": chart,
            "derived_facts": derived_facts or {},
            "citation": citation,
            "period": used_period,
            "has_attendance_data": bool(res.get("has_attendance_data", bool(rows))),
        }

    # --- 1. Daily attendance ---
    if intent == "daily_attendance":
        target_date = params.get("work_date") or datetime.date.today().isoformat()
        res = get_daily_attendance(
            conn, user, work_date=target_date, department_name=mentioned_dept,
            target_employee_id=target_emp, force_self=force_self,
        )
        rows = res["rows"]
        if not rows:
            ans = (
                f"Chưa ghi nhận bản ghi chấm công nào cho ngày {target_date} trong phạm vi quyền của bạn "
                "(dữ liệu chấm công trong hệ thống không có bản ghi cho ngày này)."
            )
            return _pack("insufficient_data", ans, res, derived_facts={"work_date": target_date}, used_period=target_date[:7])
        if force_self or len(rows) == 1:
            r = rows[0]
            in_str = r["check_in"] or "chưa ghi nhận"
            out_str = r["check_out"] or "chưa ghi nhận"
            late_mins = int(r.get("late_minutes") or 0)
            late_suffix = f" (đi muộn {late_mins} phút)" if late_mins > 0 else ""
            ans = (
                f"Ngày {r['work_date']}, nhân viên {r['employee_id']} ({r['full_name']}) có trạng thái '{r['status']}': "
                f"giờ vào {in_str}, giờ ra {out_str}, tổng {r['work_hours']} giờ công{late_suffix}."
            )
            return _pack("success", ans, res, derived_facts={"late_minutes": late_mins}, used_period=target_date[:7])
        checked_in = sum(1 for r in rows if r["check_in"])
        ans = f"Ngày {target_date} ghi nhận {len(rows)} bản ghi chấm công trong phạm vi của bạn ({checked_in} lượt có giờ vào)."
        return _pack("success", ans, res, derived_facts={"checked_in": checked_in}, used_period=target_date[:7])

    # --- 2. Employee directory ---
    if intent == "employee_directory":
        res = get_employee_directory_summary(
            conn, user, department_name=mentioned_dept, target_employee_id=target_emp, force_self=force_self,
        )
        rows = res["rows"]
        if not rows:
            return _pack("insufficient_data", "Không tìm thấy hồ sơ nhân sự hoạt động nào phù hợp trong phạm vi quyền của bạn.", res)
        scope_desc = f"Phòng {mentioned_dept}" if mentioned_dept else (
            f"Phòng {user.department_name}" if effective_scope == "department" else "Toàn công ty"
        )
        managers = res.get("managers") or []
        mgr_text = (
            "; ".join(f"{m['employee_id']} – {m['full_name']} ({m['position']})" for m in managers)
            if managers else "chưa ghi nhận trưởng phòng"
        )
        pos_sorted = sorted((res.get("positions_summary") or {}).items(), key=lambda x: -x[1])[:5]
        pos_parts = [f"{pos}: {cnt}" for pos, cnt in pos_sorted]
        ans = (
            f"{scope_desc} hiện có **{len(rows)} nhân sự đang hoạt động**.\n"
            f"- Trưởng phòng / Quản lý: {mgr_text}.\n"
            f"- Phân bổ chức danh tiêu biểu: {', '.join(pos_parts)}."
        )
        derived = {"active_count": len(rows), **{f"pos_{i}": cnt for i, (_, cnt) in enumerate(pos_sorted)}}
        return _pack("success", ans, res, derived_facts=derived)

    # --- 3. Compare two periods (TC-13) ---
    if intent == "compare_periods":
        p_a = params.get("period_a") or (explicit_periods[0] if len(explicit_periods) >= 2 else effective_period)
        p_b = params.get("period_b") or (explicit_periods[1] if len(explicit_periods) >= 2 else effective_period)
        res = compare_periods(
            conn, user, p_a, p_b, department_name=mentioned_dept, target_employee_id=target_emp, force_self=force_self,
        )
        rows = res["rows"]
        if not rows:
            return _pack("insufficient_data", f"Không đủ dữ liệu chấm công để so sánh hai kỳ {p_a} và {p_b}.", res)
        lines = [
            f"- Kỳ {r['period']}: {r['late_days']} lượt đi muộn / {r['present_days']} ngày đi làm "
            f"(tỷ lệ đi muộn {r['late_rate_pct']}%, đúng giờ {r['on_time_rate_pct']}%, tổng {r['total_work_hours']} giờ công)."
            for r in rows
        ]
        derived: Dict[str, Any] = {}
        delta_line = ""
        if len(rows) == 2:
            r1, r2 = rows[0], rows[1]
            diff_days = r2["late_days"] - r1["late_days"]
            diff_rate = round(r2["late_rate_pct"] - r1["late_rate_pct"], 2)
            derived["diff_days"] = abs(diff_days)
            derived["diff_rate"] = abs(diff_rate)
            sign_d = "+" if diff_days > 0 else ""
            sign_r = "+" if diff_rate > 0 else ""
            delta_line = (
                f"\n- Chênh lệch từ {r1['period']} sang {r2['period']}: "
                f"{sign_d}{diff_days} lượt đi muộn ({sign_r}{diff_rate} điểm % tỷ lệ đi muộn)."
            )
        scope_label = f"Phòng {mentioned_dept}" if mentioned_dept else (
            f"Phòng {user.department_name}" if effective_scope == "department" else "phạm vi của bạn"
        )
        ans = f"So sánh chấm công ({scope_label}) giữa kỳ {rows[0]['period']} và {rows[-1]['period']}:\n" + "\n".join(lines) + delta_line
        chart = {"type": "bar", "xKey": "period", "yKey": "late_rate_pct", "label": "Tỷ lệ đi muộn theo kỳ (%)", "data": rows}
        return _pack("success", ans, res, chart=chart, derived_facts=derived, used_period=f"{rows[0]['period']}..{rows[-1]['period']}")

    # --- 4. Attendance trend (TC-22) ---
    if intent == "attendance_trend":
        months = int(params.get("months") or 3)
        trend_periods = explicit_periods if (period_info.get("is_range") and not period_info.get("is_quarter")) else None
        res = get_attendance_trend(
            conn, user, months=months, periods=trend_periods, department_name=mentioned_dept, force_self=force_self,
        )
        rows = res["rows"]
        if not rows:
            return _pack("insufficient_data", "Không đủ dữ liệu chấm công để tổng hợp xu hướng theo tháng.", res)
        lines = [
            f"- Kỳ {r['period']}: {r['present_days']} ngày đi làm, {r['late_days']} lượt đi muộn ({r['late_rate_pct']}%), "
            f"đúng giờ {r['on_time_rate_pct']}%, {r['leave_days']} ngày phép, {r['absent_days']} ngày vắng."
            for r in rows
        ]
        derived = {"month_count": len(rows)}
        summary_tail = ""
        if len(rows) >= 2:
            peak = max(rows, key=lambda x: x["late_rate_pct"])
            low = min(rows, key=lambda x: x["late_rate_pct"])
            delta = round(rows[-1]["late_rate_pct"] - rows[0]["late_rate_pct"], 2)
            derived["delta_rate"] = abs(delta)
            sign = "+" if delta > 0 else ""
            summary_tail = (
                f"\nNhận xét xu hướng: Cao nhất tại kỳ {peak['period']} ({peak['late_rate_pct']}%), "
                f"thấp nhất tại kỳ {low['period']} ({low['late_rate_pct']}%), "
                f"biến động từ {rows[0]['period']} đến {rows[-1]['period']} là {sign}{delta} điểm %."
            )
        ans = f"Xu hướng chấm công {len(rows)} tháng trong phạm vi quyền của bạn:\n" + "\n".join(lines) + summary_tail
        chart = {"type": "line", "xKey": "period", "yKey": "late_rate_pct", "label": "Tỷ lệ đi muộn theo tháng (%)", "data": rows}
        return _pack("success", ans, res, chart=chart, derived_facts=derived, used_period=f"{rows[0]['period']}..{rows[-1]['period']}")

    # --- 5. Anomalies by department (TC-24) ---
    if intent == "anomalies_by_department":
        open_only = bool(params.get("open_only"))
        res = get_anomalies_by_department(
            conn, user, period=period, department_name=mentioned_dept, open_only=open_only,
        )
        rows = res["rows"]
        if not rows:
            return _pack("insufficient_data", "Hiện chưa ghi nhận cảnh báo R1-R8 nào trong phạm vi của bạn.", res, used_period=period)
        top = rows[0]
        lines = [
            f"- Phòng {r['department_name']}: {r['total_anomalies']} cảnh báo ({r['open_anomalies']} đang mở, "
            f"{r['high_anomalies']} mức cao) — Phân rã quy tắc: {r['rule_breakdown']}"
            for r in rows
        ]
        qualifier = " đang mở" if open_only else ""
        ans = (
            f"Phòng {top['department_name']} hiện có nhiều cảnh báo R1-R8{qualifier} nhất với {top['total_anomalies']} cảnh báo "
            f"({top['open_anomalies']} đang mở, {top['high_anomalies']} mức cao; gồm {top['rule_breakdown']}):\n"
            + "\n".join(lines)
        )
        chart = {
            "type": "bar",
            "xKey": "department_name",
            "yKey": "open_anomalies" if open_only else "total_anomalies",
            "label": "Số cảnh báo R1-R8 theo phòng ban",
            "data": rows,
        }
        return _pack("success", ans, res, chart=chart, used_period=period)

    # --- 6. Compare departments full (TC-21, TC-25) ---
    if intent == "compare_departments_full":
        filter_depts = params.get("department_names") or (mentioned_depts if len(mentioned_depts) >= 2 else None)
        res = compare_departments_full(conn, user, period=effective_period, department_names=filter_depts)
        rows = res["rows"]
        if not rows:
            return _pack("insufficient_data", f"Không đủ dữ liệu chấm công cho kỳ {effective_period}.", res, used_period=effective_period)
        lines = [
            f"- Phòng {r['department_name']} ({r['employee_count']} NV): đúng giờ {r['on_time_rate_pct']}%, "
            f"đi muộn {r['late_rate_pct']}% ({r['late_days']} lượt), nghỉ phép {r['leave_rate_pct']}% ({r['leave_days']} ngày), "
            f"vắng {r['absent_days']} ngày, tổng {r['total_work_hours']} giờ công, "
            f"{r['total_anomalies']} cảnh báo R1-R8 ({r['open_anomalies']} đang mở)."
            for r in rows
        ]
        top = rows[0]
        header = (
            f"So sánh hiệu suất chuyên cần giữa phòng {' và phòng '.join(filter_depts)} trong kỳ {effective_period}:\n"
            if filter_depts
            else f"So sánh toàn diện {len(rows)} phòng ban kỳ {effective_period} (Phòng {top['department_name']} có tỷ lệ đi muộn cao nhất {top['late_rate_pct']}%):\n"
        )
        ans = header + "\n".join(lines)
        chart = {"type": "bar", "xKey": "department_name", "yKey": "late_rate_pct", "label": "Tỷ lệ đi muộn (%)", "data": rows}
        return _pack("success", ans, res, chart=chart, used_period=effective_period)

    # --- 7. Compare department metrics (Standard ranking + TC-35 Turn 1 & Turn 2) ---
    if intent == "compare_department_metrics":
        res = compare_department_metrics(conn, user, period=effective_period)
        rows = res["rows"]
        if not rows:
            return _pack("insufficient_data", f"Không đủ dữ liệu chấm công cho kỳ {effective_period}.", res, used_period=effective_period)
        top = rows[0]
        ans = (
            f"Theo dữ liệu chấm công kỳ {effective_period}, phòng {top['department_name']} có tỷ lệ đi muộn cao nhất "
            f"với {top['late_rate_pct']}% ({top['late_days']} lượt đi muộn / {top['present_days']} ngày đi làm, "
            f"tỷ lệ đúng giờ {top['on_time_rate_pct']}%, tổng {top['total_work_hours']} giờ công)."
        )
        chart = {"type": "bar", "xKey": "department_name", "yKey": "late_rate_pct", "label": "Tỷ lệ đi muộn (%)", "data": rows}
        return _pack("success", ans, res, chart=chart, used_period=effective_period)

    # --- 8. Notable anomalies / Executive Risk Summary (TC-30 & S3) ---
    if intent == "notable_anomalies":
        target_p = period if period else (latest_period if "gần nhất" in sq.query_text.lower() else None)
        res = list_anomalies_tool(
            conn, user, period=target_p, severity=params.get("severity"), rule_code=params.get("rule_code"),
            department_name=mentioned_dept, target_employee_id=target_emp, force_self=force_self,
        )
        rows = res["rows"]
        if not rows:
            return _pack("insufficient_data", "Hiện tại chưa ghi nhận cảnh báo hay vấn đề chấm công nổi bật nào trong phạm vi của bạn.", res, used_period=target_p)
        top_lines = [
            f"- [{r['rule_code']} · Mức {r['severity']}] {r['target_code']} ({r['target_name']} – {r['department_name']}, kỳ {r['period']}): {r['explanation']}"
            for r in rows[:6]
        ]
        p_note = f" kỳ {target_p}" if target_p else ""
        ans = f"Các cảnh báo rủi ro chấm công nổi bật{p_note} ({len(rows)} cảnh báo R1-R8 trong phạm vi):\n" + "\n".join(top_lines)
        return _pack("success", ans, res, used_period=target_p)

    # --- 9. Anomalies list (TC-06, TC-14, TC-17, TC-27, TC-28, TC-29) ---
    if intent == "anomalies_list":
        sev = params.get("severity")
        rc = params.get("rule_code")
        res = list_anomalies_tool(
            conn, user, period=period, periods=query_periods, severity=sev, rule_code=rc,
            department_name=mentioned_dept, target_employee_id=target_emp, force_self=force_self,
        )
        rows = res["rows"]
        label = params.get("label")
        if not rows:
            avail = get_available_periods(conn)
            if period and period not in avail:
                ans = f"Không đủ dữ liệu cho kỳ {period} trong hệ thống (các kỳ hiện có: {', '.join(avail)})."
                return _pack("insufficient_data", ans, res, used_period=period)
            if label == "high_anomalies":
                return _pack("insufficient_data", "Không có cảnh báo mức cao.", res, used_period=period)
            if label == "r8_anomalies":
                return _pack("insufficient_data", "Không có nhân viên vượt quỹ phép năm (R8).", res, used_period=period)
            ans = f"Không đủ dữ liệu hoặc không ghi nhận cảnh báo bất thường nào phù hợp trong phạm vi của bạn{f' cho kỳ {period}' if period else ''}."
            return _pack("insufficient_data", ans, res, used_period=period)
        top_lines = [
            f"- [{r['rule_code']} · Mức {r['severity']}] {r['target_code']} ({r['target_name']} – {r['department_name']}, kỳ {r['period']}): {r['explanation']}"
            for r in rows[:8]
        ]
        if label == "high_anomalies":
            header = f"Cảnh báo mức độ cao ({len(rows)} bản ghi):"
        elif label == "r8_anomalies":
            header = f"Nhân viên vượt quỹ phép năm R8 ({len(rows)} bản ghi):"
        else:
            target_label = f" cho {target_emp}" if target_emp else (f" tại phòng {mentioned_dept}" if mentioned_dept else "")
            header = f"Tìm thấy {len(rows)} cảnh báo bất thường{target_label} trong phạm vi quyền của bạn{f' cho kỳ {period}' if period else ''}:"
        ans = f"{header}\n" + "\n".join(top_lines)
        return _pack("success", ans, res, used_period=period)

    # --- 10. Leave balance (TC-03, TC-15, TC-28) ---
    if intent == "leave_balance":
        threshold = params.get("threshold")
        res = get_leave_balance(
            conn, user, threshold=threshold, target_employee_id=target_emp,
            department_name=mentioned_dept, force_self=force_self,
        )
        rows = res["rows"]
        if not rows:
            return _pack("insufficient_data", "Không đủ dữ liệu hoặc không có nhân viên nào thỏa mãn điều kiện quỹ phép trong phạm vi của bạn.", res)
        derived: Dict[str, Any] = {}
        if len(rows) == 1:
            r = rows[0]
            rem = float(r["remaining_annual_days"])
            derived["over_days"] = abs(rem)
            rem_desc = f"còn lại {rem} ngày" if rem >= 0 else f"đang vượt quỹ {abs(rem)} ngày (còn {rem} ngày)"
            ans = (
                f"Nhân viên {r['employee_id']} ({r['full_name']} – Phòng {r['department_name']}) có quỹ phép năm "
                f"{r['annual_leave_balance']} ngày, đã duyệt {r['used_annual_days']} ngày (tính theo ngày lịch), {rem_desc}."
            )
        else:
            lines = [
                f"- {r['employee_id']} ({r['full_name']} – {r['department_name']}): đã dùng {r['used_annual_days']}/{r['annual_leave_balance']} ngày (còn {r['remaining_annual_days']} ngày)"
                for r in rows[:8]
            ]
            ans = f"Danh sách quỹ phép năm ({len(rows)} nhân viên trong phạm vi):\n" + "\n".join(lines)
        return _pack("success", ans, res, derived_facts=derived)

    # --- 11. Leave requests detail (TC-03 part 2, TC-12, TC-23) ---
    if intent == "leave_requests_detail":
        st_filter = params.get("status_filter")
        exec_only = params.get("requires_executive_approval")
        res = list_leave_requests_detail(
            conn, user, period=period, status_filter=st_filter, department_name=mentioned_dept,
            target_employee_id=target_emp, requires_executive_approval=exec_only, force_self=force_self,
        )
        rows = res["rows"]
        if not rows:
            ans = (
                "Hiện không có đơn nghỉ phép đặc biệt nào đang chờ Ban Điều hành phê duyệt."
                if exec_only
                else (
                    "Hiện tại bạn không có đơn nghỉ phép nào đang chờ duyệt."
                    if (st_filter == "pending" and force_self)
                    else f"Không ghi nhận đơn nghỉ phép nào phù hợp trong phạm vi quyền của bạn{f' cho kỳ {period}' if period else ''}."
                )
            )
            return _pack("insufficient_data" if not (st_filter == "pending" and force_self) else "success", ans, res, used_period=period)
        lines = [
            f"- Đơn #{r['request_id']} | {r['employee_id']} ({r['full_name']} – Phòng {r['department_name']}): "
            f"{LEAVE_TYPE_LABELS.get(r['leave_type'], r['leave_type'])}, từ {r['from_date']} đến {r['to_date']} "
            f"({r['leave_days']} ngày) · {LEAVE_STATUS_LABELS.get(r['status'], r['status'])} — Lý do: {r['reason']}"
            for r in rows[:10]
        ]
        title = (
            f"Danh sách đơn nghỉ phép đặc biệt đang chờ Ban Điều hành phê duyệt ({len(rows)} đơn):"
            if exec_only
            else f"Danh sách đơn nghỉ phép ({len(rows)} đơn trong phạm vi quyền của bạn):"
        )
        ans = f"{title}\n" + "\n".join(lines)
        return _pack("success", ans, res, used_period=period)

    # --- 12. Leave by department (TC-19) ---
    if intent == "leave_by_department":
        res = get_leave_by_department(
            conn, user, period=period, department_name=mentioned_dept,
            target_employee_id=target_emp, force_self=force_self,
        )
        rows = res["rows"]
        if not rows:
            ans = f"Không đủ dữ liệu đơn nghỉ phép trong phạm vi của bạn{f' tại phòng {mentioned_dept}' if mentioned_dept else ''}{f' cho kỳ {period}' if period else ''}."
            return _pack("insufficient_data", ans, res, used_period=period)
        lines = [
            f"- Phòng {r['department_name']}: {r['total_requests']} đơn ({r['approved_requests']} đã duyệt, "
            f"{r['pending_requests']} chờ duyệt, {r['rejected_requests']} từ chối; tổng {r['approved_leave_days']} ngày phép đã duyệt)"
            for r in rows
        ]
        ans = f"Thống kê nghỉ phép{f' phòng {mentioned_dept}' if mentioned_dept else ''}{f' kỳ {period}' if period else ''} trong phạm vi của bạn:\n" + "\n".join(lines)
        chart = (
            {"type": "bar", "xKey": "department_name", "yKey": "approved_leave_days", "label": "Số ngày nghỉ phép đã duyệt", "data": rows}
            if len(rows) > 1 else None
        )
        return _pack("success", ans, res, chart=chart, used_period=period)

    # --- 13. Employee attendance detail (TC-01, TC-05) ---
    if intent == "employee_attendance_detail":
        detail_limit = int(params.get("limit") or 31)
        order_by = str(params.get("order_by") or "date")
        filter_type = str(params.get("filter_type") or "late")
        wants_top_days = bool(params.get("wants_top_personal_days"))
        res = get_employee_attendance_detail(
            conn, user, period=None if query_periods else effective_period, periods=query_periods,
            target_employee_id=target_emp, department_name=mentioned_dept,
            filter_type=filter_type, order_by=order_by, limit=detail_limit, force_self=force_self,
        )
        rows = res["rows"]
        if not rows:
            if res.get("has_attendance_data"):
                p_cnt = int(res.get("present_days_in_scope") or 0)
                ans = f"Kỳ {effective_period} có {p_cnt} ngày đi làm trong phạm vi tra cứu và ghi nhận **0 lần đi muộn**."
                return _pack("success", ans, res, derived_facts={"late_days": 0, "present_days": p_cnt}, used_period=effective_period)
            return _pack("insufficient_data", f"Không đủ dữ liệu chấm công cho kỳ {effective_period} trong phạm vi của bạn.", res, used_period=effective_period)
        total_mins = sum(int(r.get("late_minutes") or 0) for r in rows)
        first_emp = f"{rows[0]['employee_id']} ({rows[0]['full_name']})"
        day_lines = [
            f"- {r['work_date']}: vào lúc {r['check_in']} (muộn {r['late_minutes']} phút, {r['work_hours']} giờ công)"
            for r in rows
        ]
        if wants_top_days:
            ans = f"Top {len(rows)} ngày đi muộn nhiều phút nhất của {first_emp} trong kỳ {effective_period}:\n" + "\n".join(day_lines)
        else:
            ans = (
                f"Trong kỳ {effective_period}, nhân viên {first_emp} đi muộn **{len(rows)} lần** "
                f"(tổng {total_mins} phút), cụ thể vào các ngày:\n" + "\n".join(day_lines)
            )
        return _pack("success", ans, res, derived_facts={"late_days": len(rows), "total_late_minutes": total_mins}, used_period=effective_period)

    # --- 14. Top late employees (TC-04, TC-11, TC-16 part 2, TC-26, TC-35 Turn 3) ---
    if intent == "top_late_employees":
        asking_total_count = bool(params.get("asking_total_count"))
        limit = int(params.get("limit") or (50 if asking_total_count else 5))
        res = get_top_late_employees(
            conn, user, period=None if query_periods else effective_period, periods=query_periods,
            limit=limit, department_name=mentioned_dept, target_employee_id=target_emp, force_self=force_self,
        )
        rows = res["rows"]
        if not rows:
            if res.get("has_attendance_data"):
                p_cnt = int(res.get("present_days_in_scope") or 0)
                who = f"nhân viên {target_emp}" if target_emp else (
                    f"nhân viên {user.employee_id} ({user.full_name})" if force_self else "trong phạm vi tra cứu"
                )
                ans = (
                    f"Trong kỳ {period_label}, {who} có {p_cnt} ngày đi làm "
                    "và ghi nhận **0 lần đi muộn** (đi làm đúng giờ 100%)."
                )
                return _pack("success", ans, res, derived_facts={"late_days": 0, "present_days": p_cnt, "on_time_pct": 100}, used_period=period_label)
            return _pack("insufficient_data", f"Không đủ dữ liệu hoặc không ghi nhận lượt đi muộn nào trong kỳ {period_label}.", res, used_period=period_label)
        if force_self or target_emp is not None or (len(rows) == 1 and not asking_total_count):
            r = rows[0]
            ans = (
                f"Nhân viên {r['employee_id']} ({r['full_name']} – Phòng {r['department_name']}) đi muộn "
                f"{r['late_days']} lần trong kỳ {period_label} "
                f"(tổng {r['total_late_minutes']} phút, trung bình {r['avg_late_minutes']} phút/lần)."
            )
            return _pack("success", ans, res, derived_facts={"late_days": r["late_days"]}, used_period=period_label)
        lines = [
            f"{i}. {r['employee_id']} ({r['full_name']} – {r['department_name']}): {r['late_days']} lần đi muộn (tổng {r['total_late_minutes']} phút)"
            for i, r in enumerate(rows[:10], start=1)
        ]
        dept_tail = f" tại phòng {mentioned_dept}" if mentioned_dept else ""
        prefix = (
            f"Có {len(rows)} nhân viên ghi nhận đi muộn{dept_tail}"
            if asking_total_count
            else f"Danh sách {len(rows)} nhân viên đi muộn nhiều nhất{dept_tail}"
        )
        extra = f"\n(Hiển thị 10/{len(rows)} người đi muộn nhiều nhất; xem đầy đủ trong bảng dữ liệu.)" if len(rows) > 10 else ""
        ans = f"{prefix} kỳ {period_label}:\n" + "\n".join(lines) + extra
        return _pack("success", ans, res, derived_facts={"shown_count": min(10, len(rows))}, used_period=period_label)

    # --- 15. Holidays & Overtime (TC-29 cross-check + Route H) ---
    if intent == "holidays_overtime":
        # If preceded by R7 anomalies in TC-29, cross-check OT specifically for the employee(s) found in R7!
        cross_emp = target_emp
        if cross_emp is None:
            for prev in prior_sql_evidences:
                if prev.get("intent") == "anomalies_list" and prev.get("rows"):
                    r7_emps = [
                        str(r["target_code"])
                        for r in prev["rows"]
                        if str(r.get("rule_code")) == "R7" and str(r.get("target_code", "")).startswith("NV")
                    ]
                    if len(r7_emps) == 1:
                        cross_emp = r7_emps[0]
        res = list_holidays_and_overtime(
            conn, user, period=period, target_employee_id=cross_emp,
            department_name=mentioned_dept, force_self=force_self,
        )
        hols = res.get("holidays") or []
        ot_rows = res["rows"]
        approved_ot = [r for r in ot_rows if str(r.get("status")) == "approved"]
        ask_ot = bool(params.get("ask_overtime", True))
        if ask_ot:
            emp_note = f" cho {cross_emp}" if cross_emp else ""
            period_note = f" trong kỳ {period}" if period else ""
            if ot_rows:
                ot_text = "\n".join(f"- {r['employee_id']} ({r['full_name']}) ngày {r['work_date']}: {r['status']}" for r in ot_rows[:10])
                ans = f"Đơn làm thêm giờ (OT){emp_note}{period_note} ({len(ot_rows)} đơn, trong đó {len(approved_ot)} đơn đã duyệt):\n{ot_text}"
            else:
                ans = f"Đối chiếu bảng đơn làm thêm giờ (overtime_requests){emp_note}{period_note}: ghi nhận **0 đơn tăng ca được duyệt**."
            return _pack("success", ans, res, derived_facts={"ot_total": len(ot_rows), "ot_approved": len(approved_ot)}, used_period=period)
        hol_text = ", ".join(f"{h['holiday_date']} ({h['name']})" for h in hols) if hols else "chưa có dữ liệu"
        ans = f"Danh sách ngày lễ công ty đã cấu hình ({len(hols)} ngày): {hol_text}."
        return _pack("success", ans, res, derived_facts={"holiday_count": len(hols)}, used_period=period)

    # --- 16. Default Attendance Summary ---
    res = get_attendance_summary(
        conn, user, period=None if query_periods else effective_period, periods=query_periods,
        department_name=mentioned_dept, target_employee_id=target_emp, force_self=force_self,
    )
    rows = res["rows"]
    if not rows:
        avail = get_available_periods(conn)
        hint = f" (Các kỳ hiện có dữ liệu: {', '.join(avail)})." if avail else "."
        ans = f"Không đủ dữ liệu chấm công cho kỳ {period_label} trong phạm vi của bạn{hint}"
        return _pack("insufficient_data", ans, res, derived_facts={"available_periods": ", ".join(avail)}, used_period=period_label)
    r = rows[0]
    target_prefix = f"Nhân viên {target_emp} — " if target_emp else (f"Phòng {mentioned_dept} — " if mentioned_dept else "")
    ans = (
        f"{target_prefix}Tổng hợp chấm công kỳ {r['period']} ({r['employee_count']} nhân sự trong phạm vi): "
        f"tổng {r['total_work_hours']} giờ công, {r['present_days']} ngày đi làm "
        f"(tỷ lệ đúng giờ {r['on_time_rate_pct']}%), {r['late_days']} lượt đi muộn (tỷ lệ {r['late_rate_pct']}%), "
        f"{r['missing_punch_days']} lượt thiếu chấm công, {r['leave_days']} ngày nghỉ phép ({r['leave_rate_pct']}%) "
        f"và {r['absent_days']} ngày vắng."
    )
    return _pack("success", ans, res, used_period=str(r["period"]))


def _compose_sql_answer(sql_evidences: List[Dict[str, Any]], user: AuthenticatedUser) -> Tuple[str, str, Optional[Dict[str, Any]], Optional[Dict[str, Any]], Dict[str, Any]]:
    """Combine 1 or more SQL sub-query results cleanly into answer text, status, primary table, chart, and trace."""
    if len(sql_evidences) == 1:
        ev = sql_evidences[0]
        rows = ev["rows"]
        table = {"columns": list(rows[0].keys()), "rows": rows} if rows else None
        trace = {
            "tool_name": ev["tool_name"],
            "sql_text": ev["sql_text"],
            "row_count": ev["row_count"],
            "execution_ms": round(ev["execution_ms"], 2),
        }
        return ev["status"], ev["text"], table, ev.get("chart"), trace

    # Special crisp fusion for TC-16 (attendance_summary + top_late_employees for a single employee)
    intents = [e["intent"] for e in sql_evidences]
    if intents == ["attendance_summary", "top_late_employees"] and sql_evidences[0]["rows"]:
        sum_ev, late_ev = sql_evidences[0], sql_evidences[1]
        sr = sum_ev["rows"][0]
        if late_ev["rows"]:
            lr = late_ev["rows"][0]
            emp_label = f"{lr['employee_id']} ({lr['full_name']} – Phòng {lr['department_name']})"
            late_detail = f"{lr['late_days']} lần đi muộn (tổng {lr['total_late_minutes']} phút, trung bình {lr['avg_late_minutes']} phút/lần)"
        else:
            emp_label = f"{user.employee_id} ({user.full_name})"
            late_detail = "0 lần đi muộn"
        ans = (
            f"Kỳ {sr['period']}, nhân viên {emp_label} ghi nhận {late_detail}, "
            f"tổng **{sr['total_work_hours']} giờ công** trên {sr['present_days']} ngày đi làm "
            f"(tỷ lệ đúng giờ {sr['on_time_rate_pct']}%, tỷ lệ đi muộn {sr['late_rate_pct']}%)."
        )
        rows = sum_ev["rows"]
        table = {"columns": list(rows[0].keys()), "rows": rows}
        trace = {
            "tool_name": f"{sum_ev['tool_name']}+{late_ev['tool_name']}",
            "sql_text": f"[1] {sum_ev['sql_text']} | [2] {late_ev['sql_text']}",
            "row_count": len(rows),
            "execution_ms": round(sum_ev["execution_ms"] + late_ev["execution_ms"], 2),
        }
        return "success", ans, table, None, trace

    # Special deduplicated merge for TC-17 (high anomalies + R8 anomalies)
    if intents == ["anomalies_list", "anomalies_list"]:
        e1, e2 = sql_evidences[0], sql_evidences[1]
        seen = set()
        merged_rows: List[Dict[str, Any]] = []
        for r in [*e1["rows"], *e2["rows"]]:
            aid = r.get("anomaly_id")
            if aid not in seen:
                seen.add(aid)
                merged_rows.append(r)
        overall_status = "success" if merged_rows else "insufficient_data"
        ans = f"1. {e1['text']}\n\n2. {e2['text']}" if merged_rows else "Không ghi nhận cảnh báo mức cao hay trường hợp vượt quỹ phép năm (R8) nào trong phạm vi của bạn."
        table = {"columns": list(merged_rows[0].keys()), "rows": merged_rows} if merged_rows else None
        trace = {
            "tool_name": "list_anomalies",
            "sql_text": f"[1] {e1['sql_text']} | [2] {e2['sql_text']}",
            "row_count": len(merged_rows),
            "execution_ms": round(e1["execution_ms"] + e2["execution_ms"], 2),
        }
        return overall_status, ans, table, None, trace

    # General multi-intent SQL merge
    any_success = any(e["status"] == "success" for e in sql_evidences)
    overall_status = "success" if any_success else "insufficient_data"
    sections = [f"{idx}. {e['text']}" for idx, e in enumerate(sql_evidences, start=1)]
    ans = "\n\n".join(sections)

    primary_rows: List[Dict[str, Any]] = []
    primary_chart: Optional[Dict[str, Any]] = None
    for e in sql_evidences:
        if e["rows"] and not primary_rows:
            primary_rows = e["rows"]
        if e.get("chart") and primary_chart is None:
            primary_chart = e["chart"]

    table = {"columns": list(primary_rows[0].keys()), "rows": primary_rows} if primary_rows else None
    tool_names: List[str] = []
    sql_parts: List[str] = []
    for idx, e in enumerate(sql_evidences, start=1):
        if e["tool_name"] not in tool_names:
            tool_names.append(e["tool_name"])
        if e.get("sql_text"):
            sql_parts.append(f"[{idx}] {e['sql_text']}")

    trace = {
        "tool_name": "+".join(tool_names),
        "sql_text": " | ".join(sql_parts) if sql_parts else None,
        "row_count": sum(e["row_count"] for e in sql_evidences),
        "execution_ms": round(sum(e["execution_ms"] for e in sql_evidences), 2),
    }
    return overall_status, ans, table, primary_chart, trace


class HybridOrchestrator:
    """Unified Phase 3 AI Core Orchestrator uniting:
    - Authoritative 5-role EffectiveScopeResolver & Security Pre-Guards
    - User-Isolated Conversation Context Manager (Multi-turn with Live RBAC Re-Check)
    - Multi-Intent AI Query Router (SQL_ONLY / RAG_ONLY / HYBRID / GENERAL / CLARIFICATION)
    - Fault-Isolated SQL Intelligence v2 + RAG Intelligence (BM25 + Vector / pgvector RRF)
    - Google Gemini 2.5 Flash Synthesis + Mandatory Numeric Fact Verification Gate + Deterministic Fallback
    """

    def handle_question(
        self,
        conn: Any,
        user: AuthenticatedUser,
        question: str,
        conversation_id: Optional[str] = None,
        active_period: Optional[str] = None,
        llm_provider_override: Optional[BaseLLMProvider] = None,
    ) -> Dict[str, Any]:
        q_clean = (question or "").strip()
        q_lower = q_clean.lower()

        # =====================================================================
        # 0. STRICT AUTHORITATIVE RBAC PRE-GATE (BEFORE CONVERSATION / ROUTER / LLM)
        # =====================================================================
        effective_scope = resolve_ai_effective_scope(user)
        if effective_scope == "none":
            answer = (
                "Vai trò Quản trị hệ thống (Admin) không mặc định được cấp quyền truy vấn dữ liệu nghiệp vụ nhân sự qua Trợ lý AI."
                if user.role == RoleEnum.admin
                else "Tài khoản của bạn hiện không được cấp quyền truy vấn dữ liệu qua Trợ lý AI."
            )
            return self._blocked_response(
                conn=conn, user=user, q_clean=q_clean, tool_name="rbac_guard",
                answer=answer, effective_scope=effective_scope, conversation_id=None,
                query_type="rbac_block",
            )

        # Load or create strictly user-isolated conversation session
        conv_id, prev_context, _ = get_or_create_conversation(
            conn=conn, user_id=user.user_id, conversation_id=conversation_id, initial_question=q_clean,
        )

        # =====================================================================
        # 1. SECURITY & READ-ONLY PRE-GUARDS (USER QUESTION)
        # =====================================================================
        for pattern in PROMPT_INJECTION_PATTERNS:
            if re.search(pattern, q_lower):
                answer = (
                    "Yêu cầu bị từ chối bởi lớp bảo mật hệ thống. Trợ lý AI chỉ hỗ trợ truy vấn đọc "
                    "dữ liệu chấm công, nghỉ phép và quy định nội bộ trong đúng phạm vi quyền hạn của tài khoản."
                )
                resp = self._blocked_response(
                    conn=conn, user=user, q_clean=q_clean, tool_name="security_guard",
                    answer=answer, effective_scope=effective_scope, conversation_id=conv_id,
                )
                save_conversation_turn(conn, conv_id, user.user_id, q_clean, resp, prev_context)
                return resp

        for pattern in OUT_OF_SCOPE_PATTERNS:
            if re.search(pattern, q_lower):
                answer = (
                    "Hệ thống HR Attendance Copilot chỉ quản lý dữ liệu chấm công, đơn nghỉ phép, cảnh báo bất thường "
                    "và tài liệu quy định nội bộ; hệ thống không lưu trữ dữ liệu tiền lương, thuế hay tuyển dụng."
                )
                resp = self._blocked_response(
                    conn=conn, user=user, q_clean=q_clean, tool_name="scope_policy_guard",
                    answer=answer, effective_scope=effective_scope, conversation_id=conv_id,
                )
                save_conversation_turn(conn, conv_id, user.user_id, q_clean, resp, prev_context)
                return resp

        is_policy_inquiry = bool(POLICY_INQUIRY_EXEMPT_PATTERN.search(q_lower)) and not bool(
            EXPLICIT_IMPERATIVE_WRITE_PATTERN.search(q_lower)
        )
        if not is_policy_inquiry:
            for pattern in WRITE_ACTION_PATTERNS:
                if re.search(pattern, q_lower):
                    is_leave = any(k in q_lower for k in ["đơn", "nghỉ phép", "phép"])
                    hint = (
                        "Vui lòng thực hiện trực tiếp tại màn hình Đơn nghỉ phép (/leaves) theo đúng quy trình phân quyền."
                        if is_leave
                        else "Vui lòng thực hiện trực tiếp tại màn hình nghiệp vụ tương ứng (Chấm công / Cảnh báo / Nhân sự) nếu tài khoản được cấp quyền."
                    )
                    answer = (
                        "Trợ lý AI hoạt động ở chế độ chỉ đọc (Read-Only) nên không tự thực hiện thao tác tạo, duyệt, hủy đơn "
                        f"hay chỉnh sửa dữ liệu nghiệp vụ. {hint}"
                    )
                    actions = [{"label": "Mở Đơn nghỉ phép", "path": "/leaves"}] if is_leave else []
                    resp = self._blocked_response(
                        conn=conn, user=user, q_clean=q_clean, tool_name="read_only_guard",
                        answer=answer, effective_scope=effective_scope, conversation_id=conv_id,
                        suggested_actions=actions,
                    )
                    save_conversation_turn(conn, conv_id, user.user_id, q_clean, resp, prev_context)
                    return resp

        # =====================================================================
        # 2. ENTITY EXTRACTION + MULTI-TURN CONTEXT RESOLUTION + LIVE RBAC RE-CHECK
        # =====================================================================
        emp_codes = extract_employee_codes(q_clean)
        mentioned_depts = extract_departments(q_lower, conn)
        period_info = extract_periods_info(q_lower, conn)
        if not period_info.get("explicit") and active_period and re.match(r"^20\d{2}-(0[1-9]|1[0-2])$", active_period.strip()):
            period_info["ui_hint"] = active_period.strip()
        resolved_named_emp = None if emp_codes else resolve_employee_name_in_scope(conn, user, q_clean)
        target_emp: Optional[str] = (
            emp_codes[0] if emp_codes else (resolved_named_emp["employee_id"] if resolved_named_emp else None)
        )
        force_self = effective_scope == "self" or is_explicit_self_query(
            q_lower, emp_codes, mentioned_depts, resolved_named_emp
        )
        explicit_date_m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", q_clean)

        entities: Dict[str, Any] = {
            "emp_codes": emp_codes,
            "mentioned_depts": mentioned_depts,
            "period_info": period_info,
            "target_emp": target_emp,
            "force_self": force_self,
            "rule_codes": _extract_rule_codes(q_clean),
            "severity": _extract_severity(q_lower),
            "leave_status": _extract_leave_status(q_lower),
            "explicit_date": explicit_date_m.group(1) if explicit_date_m else None,
            "latest_period": get_latest_attendance_period(conn),
        }

        # Resolve follow-up context (pronouns / period shifts) BEFORE live RBAC enforcement!
        entities, used_context = resolve_followup_entities(q_clean, entities, prev_context)

        # Preliminary route inspection so pure policy questions (e.g., "quy định công ty") are not falsely blocked
        plan: RoutingPlan = route_query(q_clean, entities, used_context=used_context)
        is_pure_policy_rag = plan.route_type == "RAG_ONLY"

        # --- MANDATORY LIVE RBAC POLICY RE-CHECK ON RESOLVED ENTITIES ---
        resolved_emp_codes: List[str] = entities.get("emp_codes") or []
        resolved_depts: List[str] = entities.get("mentioned_depts") or []

        if effective_scope == "self":
            other_emps = [e for e in resolved_emp_codes if e != user.employee_id]
            if other_emps:
                answer = (
                    f"Bạn đang đăng nhập với phạm vi cá nhân ({user.employee_id}) nên chỉ được phép tra cứu dữ liệu "
                    f"của chính mình, không có quyền xem dữ liệu của nhân viên {', '.join(other_emps)}."
                )
                resp = self._blocked_response(conn, user, q_clean, "rbac_guard", answer, effective_scope, conv_id)
                save_conversation_turn(conn, conv_id, user.user_id, q_clean, resp, prev_context)
                return resp

            has_company_or_dept_kw = (
                any(k in q_lower for k in ["phòng nào", "phòng ban nào", "toàn công ty", "các phòng", "so sánh phòng"])
                or bool(resolved_depts)
            )
            is_self_top_query = (
                "top " in q_lower
                and any(k in q_lower for k in ["ngày tôi", "của tôi", "tôi đi muộn", "lần tôi", "của mình"])
                and not any(k in q_lower for k in ["nhân viên", "người", "phòng", "công ty", "ai "])
            )
            has_forbidden_top = ("top " in q_lower) and not is_self_top_query
            if (has_company_or_dept_kw or has_forbidden_top) and not is_pure_policy_rag:
                answer = (
                    f"Vai trò Nhân viên ({user.employee_id}) chỉ xem được dữ liệu cá nhân, không có quyền xem thống kê "
                    "cấp phòng ban hoặc so sánh toàn công ty."
                )
                resp = self._blocked_response(conn, user, q_clean, "rbac_guard", answer, effective_scope, conv_id)
                save_conversation_turn(conn, conv_id, user.user_id, q_clean, resp, prev_context)
                return resp

        if effective_scope == "department":
            foreign_depts = [d for d in resolved_depts if d.lower() != user.department_name.lower()]
            if foreign_depts and not is_pure_policy_rag:
                answer = (
                    f"Bạn đang có phạm vi quản lý phòng {user.department_name}, "
                    f"không có quyền tra cứu dữ liệu của phòng {', '.join(foreign_depts)}."
                )
                resp = self._blocked_response(conn, user, q_clean, "rbac_guard", answer, effective_scope, conv_id)
                save_conversation_turn(conn, conv_id, user.user_id, q_clean, resp, prev_context)
                return resp

            if (
                any(k in q_lower for k in ["toàn công ty", "phòng nào", "phòng ban nào", "so sánh các phòng", "phòng khác"])
                and not is_pure_policy_rag
            ):
                answer = (
                    f"Vai trò Trưởng phòng {user.department_name} chỉ được phép tra cứu số liệu trong phạm vi "
                    f"phòng {user.department_name}, không được xem dữ liệu toàn công ty hoặc so sánh phòng ban khác."
                )
                resp = self._blocked_response(conn, user, q_clean, "rbac_guard", answer, effective_scope, conv_id)
                save_conversation_turn(conn, conv_id, user.user_id, q_clean, resp, prev_context)
                return resp

            if resolved_emp_codes and not is_pure_policy_rag:
                for code in resolved_emp_codes:
                    if resolve_employee_in_scope(conn, user, code) is None:
                        answer = (
                            f"Nhân viên {code} không thuộc phòng {user.department_name} mà bạn quản lý "
                            "(hoặc không tồn tại trong phạm vi của bạn), nên hệ thống từ chối cung cấp dữ liệu."
                        )
                        resp = self._blocked_response(conn, user, q_clean, "rbac_guard", answer, effective_scope, conv_id)
                        save_conversation_turn(conn, conv_id, user.user_id, q_clean, resp, prev_context)
                        return resp

        if effective_scope == "all" and resolved_emp_codes and not is_pure_policy_rag:
            missing_codes = [c for c in resolved_emp_codes if resolve_employee_in_scope(conn, user, c) is None]
            if missing_codes:
                answer = f"Không tìm thấy mã nhân viên {', '.join(missing_codes)} trong hệ thống."
                _log_audit(
                    conn, user, q_clean, "resolve_employee_in_scope", None, 0, "insufficient_data",
                    query_type="ai_sql", effective_scope=effective_scope,
                )
                resp = self._build_response(
                    status="insufficient_data",
                    answer=answer,
                    conversation_id=conv_id,
                    route=plan.to_dict(),
                    table=None,
                    chart=None,
                    trace={"tool_name": "resolve_employee_in_scope", "sql_text": None, "row_count": 0, "execution_ms": 0.0},
                    sql_citations=[],
                    rag_citations=[],
                    verification={"verified": True, "mode": "deterministic", "checked_numbers": 0, "unverified_numbers": [], "used_fallback": False},
                    llm_meta={"provider": "deterministic", "model": "deterministic_template", "used_llm": False, "used_fallback": False, "fallback_reason": None, "latency_ms": 0.0, "attempts": 0},
                    role=user.role,
                )
                save_conversation_turn(conn, conv_id, user.user_id, q_clean, resp, prev_context)
                return resp

        # =====================================================================
        # 3. GENERAL & CLARIFICATION ROUTES (ZERO SQL / ZERO HALLUCINATION)
        # =====================================================================
        if plan.route_type == "GENERAL":
            role_label = ROLE_LABELS_VI.get(user.role, user.role.value)
            scope_label = _scope_human_label(user, effective_scope)
            answer = (
                f"Xin chào {user.full_name}! Tôi là **Trợ lý AI HR Attendance Copilot** hỗ trợ tra cứu chỉ đọc (Read-Only) "
                f"theo đúng quyền **{role_label}** (phạm vi: **{scope_label}**).\n"
                "- **Dữ liệu vận hành (SQL):** chấm công theo ngày/tháng, đi muộn, quỹ phép năm, đơn nghỉ phép, cảnh báo R1-R8 và so sánh/xu hướng.\n"
                "- **Nội quy & Quy trình (RAG):** giờ làm việc, ân hạn đi muộn, quy trình xin/hủy đơn phép, quy định tăng ca và hướng dẫn xử lý R1-R8.\n"
                "- **Kết hợp (Hybrid):** đối chiếu trực tiếp số liệu thực tế với quy định công ty hiện hành kèm trích dẫn.\n"
                "Bạn hãy đặt câu hỏi cụ thể hoặc chọn một gợi ý bên dưới nhé."
            )
            _log_audit(conn, user, q_clean, "general_assistant", None, 0, "success", query_type="ai_general", effective_scope=effective_scope)
            resp = self._build_response(
                status="success",
                answer=answer,
                conversation_id=conv_id,
                route=plan.to_dict(),
                table=None,
                chart=None,
                trace={"tool_name": "general_assistant", "sql_text": None, "row_count": 0, "execution_ms": 0.0},
                sql_citations=[],
                rag_citations=[],
                verification={"verified": True, "mode": "deterministic", "checked_numbers": 0, "unverified_numbers": [], "used_fallback": False},
                llm_meta={"provider": "deterministic", "model": "deterministic_template", "used_llm": False, "used_fallback": False, "fallback_reason": None, "latency_ms": 0.0, "attempts": 0},
                role=user.role,
            )
            save_conversation_turn(conn, conv_id, user.user_id, q_clean, resp, prev_context)
            return resp

        if plan.route_type == "CLARIFICATION":
            answer = (
                "Câu hỏi của bạn hơi chung chung nên tôi chưa xác định rõ chỉ số cần tra cứu. "
                "Bạn vui lòng nêu cụ thể hơn về nội dung (đi muộn, quỹ phép năm, đơn chờ duyệt, cảnh báo bất thường, "
                "tổng hợp chấm công hoặc quy định nội bộ) và thời gian (ví dụ: tháng 10/2026) nhé."
            )
            _log_audit(conn, user, q_clean, "clarification", None, 0, "success", query_type="ai_general", effective_scope=effective_scope)
            resp = self._build_response(
                status="clarification_needed",
                answer=answer,
                conversation_id=conv_id,
                route=plan.to_dict(),
                table=None,
                chart=None,
                trace={"tool_name": "clarification", "sql_text": None, "row_count": 0, "execution_ms": 0.0},
                sql_citations=[],
                rag_citations=[],
                verification={"verified": True, "mode": "deterministic", "checked_numbers": 0, "unverified_numbers": [], "used_fallback": False},
                llm_meta={"provider": "deterministic", "model": "deterministic_template", "used_llm": False, "used_fallback": False, "fallback_reason": None, "latency_ms": 0.0, "attempts": 0},
                role=user.role,
                extra={"clarification_needed": True},
            )
            save_conversation_turn(conn, conv_id, user.user_id, q_clean, resp, prev_context)
            return resp

        # =====================================================================
        # 4. EXECUTE SQL INTELLIGENCE & FAULT-ISOLATED RAG INTELLIGENCE
        # =====================================================================
        sql_sub_queries = [sq for sq in plan.sub_queries if sq.kind == "sql"]
        rag_sub_queries = [sq for sq in plan.sub_queries if sq.kind == "rag"]

        sql_evidences: List[Dict[str, Any]] = []
        for sq in sql_sub_queries:
            ev = _execute_sql_subquery(conn, user, sq, entities, effective_scope, sql_evidences)
            sql_evidences.append(ev)

        rag_result: Optional[Dict[str, Any]] = None
        if rag_sub_queries:
            rag_q_text = rag_sub_queries[0].query_text
            # Enrich TC-30 Executive risk RAG query with actual rule codes observed in SQL (e.g. R6, R7)
            if sql_evidences:
                observed_rules: List[str] = []
                for ev in sql_evidences:
                    for row in ev.get("rows") or []:
                        rc = row.get("rule_code")
                        if rc and str(rc) not in observed_rules and str(rc).lower() not in rag_q_text.lower():
                            observed_rules.append(str(rc))
                if observed_rules:
                    rag_q_text = f"{rag_q_text} quy trình xử lý {' '.join(observed_rules[:4])}"
            rag_result = query_rag_knowledge(conn, user, rag_q_text, mode="hybrid", top_k=4)

        # =====================================================================
        # 5. COMPOSE DETERMINISTIC GROUNDED RESPONSE (CLEARLY SEPARATING SQL vs RAG)
        # =====================================================================
        sql_citations = [ev["citation"] for ev in sql_evidences]
        rag_chunks = (rag_result.get("chunks") or []) if rag_result and rag_result.get("sufficient_evidence") else []
        rag_citations = (rag_result.get("citations") or []) if rag_result and rag_result.get("sufficient_evidence") else []
        untrusted_rag_context = (rag_result.get("untrusted_context_block") or "") if rag_result else ""

        final_table: Optional[Dict[str, Any]] = None
        final_chart: Optional[Dict[str, Any]] = None
        trace: Dict[str, Any] = {"tool_name": None, "sql_text": None, "row_count": 0, "execution_ms": 0.0}
        has_insufficient_sql_only = False

        if plan.route_type == "RAG_ONLY":
            assert rag_result is not None
            if rag_result["status"] == "blocked":
                resp = self._blocked_response(
                    conn, user, q_clean, "rag_rbac_guard", rag_result["answer"], effective_scope, conv_id,
                )
                save_conversation_turn(conn, conv_id, user.user_id, q_clean, resp, prev_context)
                return resp

            if rag_result["status"] == "error":
                final_status = "error"
                deterministic_answer = rag_result["answer"]
            elif not rag_result["sufficient_evidence"]:
                final_status = "insufficient_data"
                deterministic_answer = (
                    "Không tìm thấy đủ căn cứ trong kho tài liệu nội bộ hiện hành để trả lời chính xác câu hỏi này "
                    "(hệ thống không tự suy diễn ngoài tài liệu đã được xác thực)."
                )
            else:
                final_status = "success"
                deterministic_answer = rag_result["answer"]

            rag_ms = float((rag_result.get("metrics") or {}).get("total_ms") or 0.0)
            trace = {
                "tool_name": "rag_hybrid_search",
                "sql_text": None,
                "row_count": len(rag_chunks),
                "execution_ms": round(rag_ms, 2),
            }
            q_type = "ai_rag"

        elif plan.route_type == "SQL_ONLY":
            final_status, deterministic_answer, final_table, final_chart, trace = _compose_sql_answer(sql_evidences, user)
            has_insufficient_sql_only = final_status == "insufficient_data"
            q_type = "ai_strategy" if user.role == RoleEnum.executive else "ai_sql"

        else:  # HYBRID (SQL + RAG)
            sql_status, sql_text_ans, final_table, final_chart, sql_trace = _compose_sql_answer(sql_evidences, user)
            rag_ms = float((rag_result.get("metrics") or {}).get("total_ms") or 0.0) if rag_result else 0.0
            rag_ok = bool(rag_result and rag_result.get("sufficient_evidence"))

            if rag_ok:
                rag_section = rag_result["answer"]  # type: ignore[index]
            elif rag_result and rag_result.get("status") == "error":
                rag_section = (
                    "Hệ thống tra cứu tài liệu RAG đang gặp lỗi tạm thời; phần dữ liệu SQL ở trên vẫn được xác minh đầy đủ."
                )
            else:
                rag_section = (
                    "Chưa tìm thấy điều khoản quy định đủ căn cứ trong kho tài liệu nội bộ hiện hành cho phần chính sách này."
                )

            # Neutral cross-reference note for TC-26 (late days vs R1 threshold) without fabricating numbers
            neutral_note = ""
            if "chạm ngưỡng" in q_lower and "r1" in q_lower and sql_evidences and sql_evidences[0]["rows"]:
                r0 = sql_evidences[0]["rows"][0]
                late_d = int(r0.get("late_days") or 0)
                if late_d >= 5:
                    neutral_note = (
                        f"\n\n**Đối chiếu trung tính:** Với {late_d} lần đi muộn trong kỳ (≥ 5 ngày theo Quy tắc R1), "
                        "mức này chạm ngưỡng kích hoạt cảnh báo kỹ thuật R1 để đối chiếu xác minh (chưa phải kết luận vi phạm kỷ luật)."
                    )
                else:
                    neutral_note = (
                        f"\n\n**Đối chiếu trung tính:** Với {late_d} lần đi muộn trong kỳ (< 5 ngày theo Quy tắc R1), "
                        "mức này chưa chạm ngưỡng kích hoạt cảnh báo kỹ thuật R1."
                    )
            elif any(ev["intent"] in ("anomalies_list", "notable_anomalies") for ev in sql_evidences):
                neutral_note = (
                    "\n\n*Lưu ý trung tính: Mọi cảnh báo R1-R8 là dấu hiệu kỹ thuật hỗ trợ kiểm tra đối chiếu, "
                    "không phải kết luận vi phạm kỷ luật.*"
                )

            deterministic_answer = (
                f"### 1. Dữ liệu thực tế từ hệ thống (SQL)\n{sql_text_ans}\n\n"
                f"### 2. Căn cứ quy định & quy trình nội bộ (RAG)\n{rag_section}{neutral_note}"
            )
            final_status = "success" if (sql_status == "success" or rag_ok) else "insufficient_data"
            has_insufficient_sql_only = (sql_status == "insufficient_data" and not rag_ok)
            trace = {
                "tool_name": f"{sql_trace['tool_name']}+rag_hybrid_search",
                "sql_text": sql_trace["sql_text"],
                "row_count": sql_trace["row_count"],
                "execution_ms": round(float(sql_trace["execution_ms"]) + rag_ms, 2),
            }
            q_type = "ai_hybrid"

        # =====================================================================
        # 6. OPTIONAL GEMINI 2.5 FLASH SYNTHESIS + MANDATORY NUMERIC FACT VERIFICATION GATE
        # =====================================================================
        extra_verified_texts = [
            str((entities.get("period_info") or {}).get("primary") or ""),
            str(entities.get("latest_period") or ""),
        ]
        # Verify deterministic baseline first
        det_check = verify_response_facts(
            candidate_text=deterministic_answer,
            sql_evidences=sql_evidences,
            rag_chunks=rag_chunks,
            extra_verified_texts=[*extra_verified_texts, deterministic_answer],
            has_insufficient_sql_only=has_insufficient_sql_only,
        )

        final_answer = deterministic_answer
        llm_meta: Dict[str, Any] = {
            "provider": "deterministic",
            "model": "deterministic_template",
            "used_llm": False,
            "used_fallback": False,
            "fallback_reason": None,
            "latency_ms": 0.0,
            "attempts": 0,
        }
        verification_info: Dict[str, Any] = {
            "verified": det_check["verified"],
            "mode": "deterministic",
            "checked_numbers": det_check["checked_numbers"],
            "unverified_numbers": det_check["unverified_numbers"],
            "sql_fact_count": det_check["sql_fact_count"],
            "rag_fact_count": det_check["rag_fact_count"],
            "used_fallback": False,
            "llm_output_rejected": False,
            "flagged_unverified_numbers": [],
        }

        # Only invoke Gemini 2.5 Flash when evidence is sufficient & status is 'success' (never synthesize over empty/missing data!)
        if final_status == "success":
            llm_res = synthesize_with_gemini(
                conn=conn,
                question=q_clean,
                role_label=ROLE_LABELS_VI.get(user.role, user.role.value),
                scope_label=_scope_human_label(user, effective_scope, force_self=bool(entities.get("force_self"))),
                route_type=plan.route_type,
                sql_evidence_summary=sql_evidences,
                untrusted_rag_context=untrusted_rag_context,
                deterministic_draft=deterministic_answer,
                provider_override=llm_provider_override,
            )
            llm_meta = llm_res.to_meta()

            if llm_res.ok and llm_res.text:
                llm_check = verify_response_facts(
                    candidate_text=llm_res.text,
                    sql_evidences=sql_evidences,
                    rag_chunks=rag_chunks,
                    extra_verified_texts=extra_verified_texts,
                    has_insufficient_sql_only=has_insufficient_sql_only,
                )
                has_accusatory = any(re.search(p, llm_res.text.lower()) for p in ACCUSATORY_PATTERNS)
                if llm_check["verified"] and not has_accusatory:
                    final_answer = llm_res.text
                    verification_info = {
                        "verified": True,
                        "mode": "gemini_verified",
                        "checked_numbers": llm_check["checked_numbers"],
                        "unverified_numbers": [],
                        "sql_fact_count": llm_check["sql_fact_count"],
                        "rag_fact_count": llm_check["rag_fact_count"],
                        "used_fallback": False,
                        "llm_output_rejected": False,
                        "flagged_unverified_numbers": [],
                    }
                else:
                    # MANDATORY SAFETY GATE: Reject fabricated/unverified Gemini output -> Deterministic verified fallback!
                    flagged = list(llm_check["unverified_numbers"])
                    if has_accusatory:
                        flagged.append("<accusatory_verdict>")
                    llm_meta["used_llm"] = False
                    llm_meta["used_fallback"] = True
                    llm_meta["fallback_reason"] = "numeric_fact_verification_failed"
                    verification_info = {
                        "verified": det_check["verified"],
                        "mode": "deterministic_fallback_after_mismatch",
                        "checked_numbers": det_check["checked_numbers"],
                        "unverified_numbers": [],
                        "sql_fact_count": det_check["sql_fact_count"],
                        "rag_fact_count": det_check["rag_fact_count"],
                        "used_fallback": True,
                        "llm_output_rejected": True,
                        "flagged_unverified_numbers": flagged,
                    }
            else:
                verification_info["mode"] = (
                    "deterministic" if llm_res.error_code == "missing_api_key" else "deterministic_fallback_llm_unavailable"
                )
                verification_info["used_fallback"] = True

        # =====================================================================
        # 7. LOG AUDIT, PERSIST CONVERSATION TURN & RETURN UNIFIED RESPONSE
        # =====================================================================
        _log_audit(
            conn=conn,
            user=user,
            question=q_clean,
            tool_name=trace["tool_name"],
            sql_text=trace["sql_text"],
            row_count=int(trace["row_count"] or 0),
            status=final_status,
            query_type=q_type,
            effective_scope=effective_scope,
        )

        primary_sql_intent = sql_sub_queries[0].intent if sql_sub_queries else None
        entities["effective_period"] = (entities.get("period_info") or {}).get("primary") or entities.get("latest_period")
        new_context = build_updated_context_state(
            prev_state=prev_context,
            question=q_clean,
            route_type=plan.route_type,
            primary_sql_intent=primary_sql_intent,
            entities=entities,
            sql_evidences=sql_evidences,
        )

        actions = _suggested_actions_for(q_lower, plan.route_type, [sq.intent for sq in sql_sub_queries])
        resp = self._build_response(
            status=final_status,
            answer=final_answer,
            conversation_id=conv_id,
            route=plan.to_dict(),
            table=final_table,
            chart=final_chart,
            trace=trace,
            sql_citations=sql_citations,
            rag_citations=rag_citations,
            verification=verification_info,
            llm_meta=llm_meta,
            role=user.role,
            suggested_actions=actions,
        )
        save_conversation_turn(conn, conv_id, user.user_id, q_clean, resp, new_context)
        return resp

    def _blocked_response(
        self,
        conn: Any,
        user: AuthenticatedUser,
        q_clean: str,
        tool_name: str,
        answer: str,
        effective_scope: str,
        conversation_id: Optional[str],
        query_type: str = "rbac_block",
        suggested_actions: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        _log_audit(
            conn, user, q_clean, tool_name, None, 0, "blocked",
            query_type=query_type, effective_scope=effective_scope,
        )
        return self._build_response(
            status="blocked",
            answer=answer,
            conversation_id=conversation_id,
            route={"type": "BLOCKED", "sub_queries": [], "rationale": tool_name, "used_context": False, "is_multi_intent": False},
            table=None,
            chart=None,
            trace={"tool_name": tool_name, "sql_text": None, "row_count": 0, "execution_ms": 0.0},
            sql_citations=[],
            rag_citations=[],
            verification={"verified": True, "mode": "security_gate", "checked_numbers": 0, "unverified_numbers": [], "used_fallback": False},
            llm_meta={"provider": "none", "model": "none", "used_llm": False, "used_fallback": False, "fallback_reason": "blocked_before_llm", "latency_ms": 0.0, "attempts": 0},
            role=user.role,
            suggested_followups=[] if effective_scope == "none" else get_suggested_prompts(user.role),
            suggested_actions=suggested_actions or [],
        )

    def _build_response(
        self,
        status: str,
        answer: str,
        conversation_id: Optional[str],
        route: Dict[str, Any],
        table: Optional[Dict[str, Any]],
        chart: Optional[Dict[str, Any]],
        trace: Dict[str, Any],
        sql_citations: List[Dict[str, Any]],
        rag_citations: List[Dict[str, Any]],
        verification: Dict[str, Any],
        llm_meta: Dict[str, Any],
        role: RoleEnum,
        suggested_followups: Optional[List[str]] = None,
        suggested_actions: Optional[List[Dict[str, str]]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        col_labels = _column_labels_for(table["columns"]) if table and table.get("columns") else {}
        payload: Dict[str, Any] = {
            "status": status,
            "answer": answer,
            "conversation_id": conversation_id,
            "route": route,
            "table": table,
            "column_labels": col_labels,
            "chart": chart,
            "citations": {
                "sql": sql_citations,
                "rag": rag_citations,
            },
            "trace": trace,
            "verification": verification,
            "llm": llm_meta,
            "suggested_followups": suggested_followups if suggested_followups is not None else get_suggested_prompts(role),
            "suggested_actions": suggested_actions or [],
        }
        if extra:
            payload.update(extra)
        return payload


_ORCHESTRATOR = HybridOrchestrator()


def answer_question_hybrid(
    conn: Any,
    user: AuthenticatedUser,
    question: str,
    conversation_id: Optional[str] = None,
    active_period: Optional[str] = None,
    llm_provider_override: Optional[BaseLLMProvider] = None,
) -> Dict[str, Any]:
    return _ORCHESTRATOR.handle_question(
        conn=conn,
        user=user,
        question=question,
        conversation_id=conversation_id,
        active_period=active_period,
        llm_provider_override=llm_provider_override,
    )
