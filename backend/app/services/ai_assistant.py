from __future__ import annotations

import datetime
import re
import sqlite3
from typing import Any, Dict, List, Optional

from app.core.security import AuthenticatedUser, resolve_ai_effective_scope
from app.schemas.common import RoleEnum
from app.services.ai_entities import (
    extract_departments,
    extract_employee_codes,
    extract_periods_info,
    get_available_periods,
    get_latest_attendance_period,
    is_explicit_self_query,
    resolve_employee_name_in_scope,
)
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

# Hardened Prompt Injection / Security Attack Guard:
# Blocks data exfiltration, SQL injection, privilege escalation, and instruction override WITHOUT
# false-positively blocking benign self-service questions like "Làm sao để tôi đổi mật khẩu tài khoản của mình?".
PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous",
    r"bỏ\s*qua\s+(mọi\s+)?hướng\s*dẫn",
    r"quên\s+hướng\s*dẫn",
    r"đổi\s+quyền",
    r"nâng\s+quyền",
    r"set\s+role",
    r"drop\s+table",
    r"delete\s+from",
    r"update\s+employees",
    r"password_hash",
    r"(?:in|xuất|xem|lấy|dump|select|show|liệt\s*kê|trích|đọc)\b.{0,30}\b(?:mật\s*khẩu|password)\b",
    r"\b(?:mật\s*khẩu|password)\s+(?:của|người|admin|hr|giám\s*đốc|trưởng\s*phòng|nhân\s*viên|tài\s*khoản\s+khác)\b",
    r"\bbảng\s+users\b",
    r"system\s*prompt",
    r"bypass\s+rbac",
    r"show\s+all\s+tables",
    r"sqlite_master",
    r"pg_catalog",
    r"information_schema",
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

# Read-Only Write-Action Guard: AI must NEVER execute mutations (create/approve/reject/cancel/edit/delete).
WRITE_ACTION_PATTERNS = [
    r"(?:hãy\s+|nhờ\s+|vui\s+lòng\s+)?(?:tạo|đăng\s*ký|gửi)\s+(?:giúp\s+(?:tôi\s+)?)?(?:một\s+)?đơn\s+(?:xin\s+)?(?:nghỉ\s*phép|phép|tăng\s*ca)",
    r"(?:hãy\s+|nhờ\s+)?(?:phê\s*duyệt|duyệt|từ\s*chối|hủy)\s+(?:ngay\s+|giúp\s+(?:tôi\s+)?)?đơn\b",
    r"(?:hãy\s+|nhờ\s+)?(?:sửa|điều\s*chỉnh|chỉnh\s*sửa|cập\s*nhật|xóa)\s+(?:giúp\s+(?:tôi\s+)?)?(?:giờ\s+)?(?:chấm\s*công|giờ\s+vào|giờ\s+ra|nhân\s*viên|tài\s*khoản|cảnh\s*báo)",
    r"(?:hãy\s+|nhờ\s+)?(?:thêm\s+mới|tạo\s+mới|khóa)\s+(?:giúp\s+(?:tôi\s+)?)?(?:nhân\s*viên|tài\s*khoản)",
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


def get_suggested_prompts(role: RoleEnum) -> List[str]:
    if role == RoleEnum.employee:
        return [
            "Tháng 10/2026 tôi đi muộn bao nhiêu lần và cụ thể vào những ngày nào?",
            "Tôi còn bao nhiêu ngày phép năm và có đơn nghỉ phép nào đang chờ duyệt không?",
            "Tổng hợp chấm công của tôi tháng 10/2026",
            "Tôi có cảnh báo bất thường nào không?",
        ]
    if role == RoleEnum.manager:
        return [
            "Tổng hợp chấm công phòng tôi tháng 10/2026",
            "Phòng tôi hiện có những đơn nghỉ phép nào đang chờ duyệt?",
            "So sánh tình hình đi muộn của phòng tôi giữa tháng 09/2026 và tháng 10/2026",
            "Phòng tôi có cảnh báo bất thường nào tháng 10/2026?",
        ]
    if role == RoleEnum.executive:
        return [
            "Phòng ban nào có tỷ lệ đi muộn cao nhất?",
            "Xu hướng chấm công 6 tháng gần đây thế nào?",
            "Hiện có những đơn nghỉ phép đặc biệt nào đang chờ Ban Điều hành phê duyệt?",
            "Phòng nào có nhiều cảnh báo R1-R8 nhất?",
        ]
    if role == RoleEnum.admin:
        return []
    return [
        "Phòng nào có tỷ lệ đi muộn cao nhất tháng 10/2026?",
        "Liệt kê top 5 nhân viên đi muộn nhiều nhất tháng 10/2026",
        "Thống kê nghỉ phép theo phòng ban tháng 10/2026",
        "Liệt kê các cảnh báo bất thường mức cao",
        "Phòng Kỹ thuật hiện có bao nhiêu nhân sự và ai là Trưởng phòng?",
    ]


def _extract_limit(q_lower: str, default: int = 5) -> int:
    m = re.search(r"\b(?:top|liệt\s*kê)\s+(\d{1,2})\b", q_lower)
    if m:
        return max(1, min(int(m.group(1)), 50))
    return default


def _extract_threshold(q_lower: str) -> Optional[float]:
    m = re.search(r"(?:dưới|nhỏ\s*hơn|ít\s*hơn|<=?)\s*(\d+(?:\.\d+)?)\s*ngày", q_lower)
    if m:
        return float(m.group(1))
    return None


def _extract_severity(q_lower: str) -> Optional[str]:
    if "mức cao" in q_lower or "mức độ cao" in q_lower or "high" in q_lower or "nghiêm trọng" in q_lower:
        return "high"
    if "trung bình" in q_lower or "medium" in q_lower:
        return "medium"
    if "mức thấp" in q_lower or "mức độ thấp" in q_lower or "low" in q_lower:
        return "low"
    return None


def _extract_rule_codes(question: str) -> List[str]:
    found: List[str] = []
    for m in re.findall(r"\b(R[1-8])\b", question, flags=re.IGNORECASE):
        u = m.upper()
        if u not in found:
            found.append(u)
    return found


def _extract_leave_status(q_lower: str) -> Optional[str]:
    if "chờ duyệt" in q_lower or "chờ phê duyệt" in q_lower or "đang chờ" in q_lower or "pending" in q_lower:
        return "pending"
    if "đã duyệt" in q_lower or "được duyệt" in q_lower or "approved" in q_lower:
        return "approved"
    if "từ chối" in q_lower or "bị từ chối" in q_lower or "rejected" in q_lower:
        return "rejected"
    if "đã hủy" in q_lower or "cancelled" in q_lower:
        return "cancelled"
    return None


def _scope_audit_label(user: AuthenticatedUser, effective_scope: str) -> str:
    if user.role == RoleEnum.admin or effective_scope == "none":
        return "system" if user.role == RoleEnum.admin else "none"
    return effective_scope


def _log_audit(
    conn: sqlite3.Connection,
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


def _blocked_response(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    q_clean: str,
    tool_name: str,
    answer: str,
    effective_scope: str,
    query_type: str = "rbac_block",
) -> Dict[str, Any]:
    _log_audit(
        conn, user, q_clean, tool_name, None, 0, "blocked",
        query_type=query_type, effective_scope=effective_scope,
    )
    return {
        "status": "blocked",
        "answer": answer,
        "table": None,
        "chart": None,
        "trace": {"tool_name": tool_name, "sql_text": None, "row_count": 0, "execution_ms": 0.0},
        "suggested_followups": [] if effective_scope == "none" else get_suggested_prompts(user.role),
    }


def answer_question(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    question: str,
) -> Dict[str, Any]:
    q_clean = question.strip()
    q_lower = q_clean.lower()

    # 0. Strict EffectiveScopeResolver RBAC Guard (intersection of user.role and live DB permissions)
    effective_scope = resolve_ai_effective_scope(user)
    if effective_scope == "none":
        answer = (
            "Vai trò Quản trị hệ thống (Admin) không mặc định được cấp quyền truy vấn dữ liệu nghiệp vụ nhân sự qua Trợ lý AI."
            if user.role == RoleEnum.admin
            else "Tài khoản của bạn hiện không được cấp quyền truy vấn dữ liệu qua Trợ lý AI."
        )
        return _blocked_response(conn, user, q_clean, "rbac_guard", answer, effective_scope, query_type="rbac_block")

    # 1. Prompt Injection / Security Attack Guard
    for pattern in PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, q_lower):
            answer = (
                "Yêu cầu bị từ chối bởi lớp bảo mật hệ thống. Trợ lý AI chỉ hỗ trợ truy vấn đọc "
                "dữ liệu chấm công và nghỉ phép trong đúng phạm vi quyền hạn của tài khoản."
            )
            return _blocked_response(conn, user, q_clean, "security_guard", answer, effective_scope)

    # 2. Out-of-scope Guard (Payroll / Salary / Recruitment)
    for pattern in OUT_OF_SCOPE_PATTERNS:
        if re.search(pattern, q_lower):
            answer = (
                "Hệ thống HR Attendance Copilot chỉ quản lý dữ liệu chấm công, đơn nghỉ phép và cảnh báo bất thường; "
                "hệ thống không lưu trữ dữ liệu tiền lương, thuế hay tuyển dụng."
            )
            return _blocked_response(conn, user, q_clean, "scope_policy_guard", answer, effective_scope)

    # 2.5. Read-Only Write-Action Guard (AI must NEVER execute business mutations)
    for pattern in WRITE_ACTION_PATTERNS:
        if re.search(pattern, q_lower):
            hint = (
                "Vui lòng thực hiện trực tiếp tại màn hình Đơn nghỉ phép (/leaves) theo đúng quy trình phân quyền."
                if any(k in q_lower for k in ["đơn", "nghỉ phép", "phép"])
                else "Vui lòng thực hiện trực tiếp tại màn hình nghiệp vụ tương ứng (Chấm công / Cảnh báo / Nhân sự) nếu tài khoản được cấp quyền."
            )
            answer = (
                "Trợ lý AI hoạt động ở chế độ chỉ đọc (Read-Only) nên không tự thực hiện thao tác tạo, duyệt, hủy đơn "
                f"hay chỉnh sửa dữ liệu nghiệp vụ. {hint}"
            )
            return _blocked_response(conn, user, q_clean, "read_only_guard", answer, effective_scope)

    # 3. Extract entities dynamically from DB & enforce EffectiveScopeResolver boundaries
    emp_codes = extract_employee_codes(q_clean)
    mentioned_depts = extract_departments(q_lower, conn)
    mentioned_dept = mentioned_depts[0] if mentioned_depts else None
    period_info = extract_periods_info(q_lower, conn)
    explicit_periods: List[str] = period_info["periods"]
    period: Optional[str] = period_info["primary"]

    # 3A. Self-only effective scope (Employee, or Manager/HR/Executive narrowed to ai.ask.self)
    if effective_scope == "self":
        other_emps = [e for e in emp_codes if e != user.employee_id]
        if other_emps:
            answer = (
                f"Bạn đang đăng nhập với phạm vi cá nhân ({user.employee_id}) nên chỉ được phép tra cứu dữ liệu "
                f"của chính mình, không có quyền xem dữ liệu của nhân viên {', '.join(other_emps)}."
            )
            return _blocked_response(conn, user, q_clean, "rbac_guard", answer, effective_scope)

        # Allow self-scoped "top N ngày tôi đi muộn..." while still blocking "top N nhân viên/người/phòng"
        has_company_or_dept_kw = any(
            k in q_lower for k in ["phòng nào", "phòng ban nào", "toàn công ty", "các phòng", "so sánh phòng"]
        ) or (mentioned_dept is not None)
        is_self_top_query = (
            "top " in q_lower
            and any(k in q_lower for k in ["ngày tôi", "của tôi", "tôi đi muộn", "lần tôi", "của mình"])
            and not any(k in q_lower for k in ["nhân viên", "người", "phòng", "công ty", "ai "])
        )
        has_forbidden_top = ("top " in q_lower) and not is_self_top_query

        if has_company_or_dept_kw or has_forbidden_top:
            answer = (
                f"Vai trò Nhân viên ({user.employee_id}) chỉ xem được dữ liệu cá nhân, không có quyền xem thống kê "
                "cấp phòng ban hoặc so sánh toàn công ty."
            )
            return _blocked_response(conn, user, q_clean, "rbac_guard", answer, effective_scope)

    # 3B. Department-only effective scope (Manager, or HR/Executive narrowed to ai.ask.department)
    if effective_scope == "department":
        foreign_depts = [d for d in mentioned_depts if d.lower() != user.department_name.lower()]
        if foreign_depts:
            answer = (
                f"Bạn đang có phạm vi quản lý phòng {user.department_name}, "
                f"không có quyền tra cứu dữ liệu của phòng {', '.join(foreign_depts)}."
            )
            return _blocked_response(conn, user, q_clean, "rbac_guard", answer, effective_scope)

        if any(k in q_lower for k in ["toàn công ty", "phòng nào", "phòng ban nào", "so sánh các phòng", "phòng khác"]):
            answer = (
                f"Vai trò Trưởng phòng {user.department_name} chỉ được phép tra cứu số liệu trong phạm vi "
                f"phòng {user.department_name}, không được xem dữ liệu toàn công ty hoặc so sánh phòng ban khác."
            )
            return _blocked_response(conn, user, q_clean, "rbac_guard", answer, effective_scope)

        if emp_codes:
            for code in emp_codes:
                # Uniform anti-enumeration response for both outside-department and non-existent codes (test_sec09)
                found_in_dept = resolve_employee_in_scope(conn, user, code)
                if found_in_dept is None:
                    answer = (
                        f"Nhân viên {code} không thuộc phòng {user.department_name} mà bạn quản lý "
                        "(hoặc không tồn tại trong phạm vi của bạn), nên hệ thống từ chối cung cấp dữ liệu."
                    )
                    return _blocked_response(conn, user, q_clean, "rbac_guard", answer, effective_scope)

    # 3C. Company-wide scope: verify explicitly mentioned employee codes exist (TC-20: NV999 -> honest insufficient_data)
    if effective_scope == "all" and emp_codes:
        missing_codes = [c for c in emp_codes if resolve_employee_in_scope(conn, user, c) is None]
        if missing_codes:
            answer = f"Không tìm thấy mã nhân viên {', '.join(missing_codes)} trong hệ thống."
            _log_audit(
                conn, user, q_clean, "resolve_employee_in_scope", None, 0, "insufficient_data",
                effective_scope=effective_scope,
            )
            return {
                "status": "insufficient_data",
                "answer": answer,
                "table": None,
                "chart": None,
                "trace": {"tool_name": "resolve_employee_in_scope", "sql_text": None, "row_count": 0, "execution_ms": 0.0},
                "suggested_followups": get_suggested_prompts(user.role),
            }

    # Resolve full name ONLY inside authoritative RBAC scope (zero cross-scope name leakage!)
    resolved_named_emp = None
    if not emp_codes:
        resolved_named_emp = resolve_employee_name_in_scope(conn, user, q_clean)

    target_emp: Optional[str] = (
        emp_codes[0] if emp_codes else (resolved_named_emp["employee_id"] if resolved_named_emp else None)
    )
    force_self = effective_scope == "self" or is_explicit_self_query(
        q_lower, emp_codes, mentioned_depts, resolved_named_emp
    )

    # 4. Safe Self-Service Account Help (TC-09: avoid false prompt-injection block & give helpful guidance)
    if any(k in q_lower for k in ["đổi mật khẩu", "thay đổi mật khẩu", "cập nhật mật khẩu"]):
        answer = (
            "Để đổi mật khẩu tài khoản của chính bạn, hãy truy cập mục **Hồ sơ cá nhân** (`/profile`), "
            "chọn phần **Đổi mật khẩu**, nhập mật khẩu hiện tại và mật khẩu mới (tối thiểu 6 ký tự). "
            "Trợ lý AI không xem hoặc thay đổi mật khẩu thay người dùng."
        )
        _log_audit(conn, user, q_clean, "self_service_guidance", None, 0, "success", effective_scope=effective_scope)
        return {
            "status": "success",
            "answer": answer,
            "table": None,
            "chart": None,
            "trace": {"tool_name": "self_service_guidance", "sql_text": None, "row_count": 0, "execution_ms": 0.0},
            "suggested_followups": get_suggested_prompts(user.role),
        }

    # 5. Ambiguous / too-short / generic domain-only question check -> ask clarifying question (no SQL executed)
    domain_keywords = [
        "đi muộn", "trễ", "chấm công", "attendance", "giờ công", "nghỉ phép", "phép", "quỹ phép",
        "cảnh báo", "bất thường", "thiếu chấm", "quên chấm", "cuối tuần", "trùng",
        "r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "so sánh", "phòng ban", "phòng nào",
        "nv0", "tổng hợp", "chuyên cần", "thống kê tháng", "xu hướng", "nổi bật", "3 tháng", "6 tháng",
        "nhân sự", "trưởng phòng", "danh sách nhân viên", "chờ duyệt", "phê duyệt", "ban điều hành",
        "đơn nghỉ", "đơn phép", "tăng ca", "ngày lễ", "đúng giờ", "hiệu suất", "mật độ rủi ro",
    ]
    generic_ambiguous_queries = {
        "chấm công", "nghỉ phép", "cảnh báo", "báo cáo", "bất thường",
        "đi muộn", "phép năm", "nhân sự", "thống kê", "tổng hợp",
        "xem chấm công", "xem nghỉ phép", "xem cảnh báo", "xem báo cáo",
    }
    severity = _extract_severity(q_lower)
    rule_codes = _extract_rule_codes(q_clean)
    rule_code = rule_codes[0] if rule_codes else None
    q_norm = re.sub(r"[?!.,:;]+$", "", q_lower).strip()
    words = [w for w in q_norm.split() if w]

    is_generic_short = (
        q_norm in generic_ambiguous_queries
        or (len(words) <= 2 and not emp_codes and not resolved_named_emp and not rule_code and not period and not severity)
    )
    if len(q_clean) < 8 or (not any(k in q_lower for k in domain_keywords) and not resolved_named_emp and not emp_codes) or is_generic_short:
        answer = (
            "Câu hỏi của bạn hơi chung chung nên tôi chưa xác định rõ chỉ số cần tra cứu. "
            "Bạn vui lòng nêu cụ thể hơn về nội dung (đi muộn, quỹ phép năm, đơn chờ duyệt, cảnh báo bất thường, "
            "hay tổng hợp chấm công) và thời gian (ví dụ: tháng 10/2026) nhé."
        )
        _log_audit(conn, user, q_clean, "clarification", None, 0, "success", effective_scope=effective_scope)
        return {
            "status": "clarification_needed",
            "clarification_needed": True,
            "answer": answer,
            "table": None,
            "chart": None,
            "trace": {"tool_name": "clarification", "sql_text": None, "row_count": 0, "execution_ms": 0.0},
            "suggested_followups": get_suggested_prompts(user.role),
        }

    latest_period = get_latest_attendance_period(conn)
    effective_period = period or latest_period
    query_periods: Optional[List[str]] = explicit_periods if (period_info["is_range"] or period_info["is_quarter"]) else None
    q_type = "ai_strategy" if user.role == RoleEnum.executive else "ai_sql"

    # =========================================================================
    # 6. DETERMINISTIC SQL INTELLIGENCE v2 ROUTING (100% SQL-COMPUTED NUMBERS)
    # =========================================================================

    # Route 0: Daily attendance check ("Hôm nay tôi đã chấm công chưa?" / explicit YYYY-MM-DD)
    explicit_date_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", q_clean)
    if (
        ("hôm nay" in q_lower or explicit_date_match is not None)
        and any(k in q_lower for k in ["chấm công", "check-in", "check in", "đi làm", "vào ca", "ra ca"])
        and not any(k in q_lower for k in ["cảnh báo", "bất thường", "quỹ phép"])
    ):
        target_date = explicit_date_match.group(1) if explicit_date_match else datetime.date.today().isoformat()
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
            _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "insufficient_data", query_type=q_type, effective_scope=effective_scope)
            return _format_response("insufficient_data", ans, res, None, user.role)

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
        else:
            checked_in = sum(1 for r in rows if r["check_in"])
            ans = (
                f"Ngày {target_date} ghi nhận {len(rows)} bản ghi chấm công trong phạm vi của bạn "
                f"({checked_in} lượt có giờ vào)."
            )
        _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], len(rows), "success", query_type=q_type, effective_scope=effective_scope)
        return _format_response("success", ans, res, None, user.role)

    # Route 0.5: Employee Directory & Department Manager (TC-18: "Phòng Kỹ thuật hiện có bao nhiêu nhân sự và ai là Trưởng phòng?")
    if (
        any(k in q_lower for k in ["bao nhiêu nhân sự", "bao nhiêu nhân viên", "ai là trưởng phòng", "trưởng phòng là ai", "danh sách nhân viên", "cơ cấu nhân sự", "chức danh"])
        and not any(k in q_lower for k in ["đi muộn", "trễ", "nghỉ phép", "cảnh báo", "bất thường", "quỹ phép"])
    ):
        res = get_employee_directory_summary(
            conn, user, department_name=mentioned_dept, target_employee_id=target_emp, force_self=force_self,
        )
        rows = res["rows"]
        if not rows:
            ans = "Không tìm thấy hồ sơ nhân sự hoạt động nào phù hợp trong phạm vi quyền của bạn."
            _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "insufficient_data", query_type=q_type, effective_scope=effective_scope)
            return _format_response("insufficient_data", ans, res, None, user.role)

        scope_desc = f"Phòng {mentioned_dept}" if mentioned_dept else (
            f"Phòng {user.department_name}" if effective_scope == "department" else "toàn công ty"
        )
        managers = res.get("managers") or []
        mgr_text = (
            "; ".join(f"{m['employee_id']} – {m['full_name']} ({m['position']})" for m in managers)
            if managers else "chưa ghi nhận trưởng phòng"
        )
        pos_parts = [f"{pos}: {cnt}" for pos, cnt in sorted(res.get("positions_summary", {}).items(), key=lambda x: -x[1])[:5]]
        ans = (
            f"{scope_desc} hiện có **{len(rows)} nhân sự đang hoạt động**.\n"
            f"- Trưởng phòng / Quản lý: {mgr_text}.\n"
            f"- Phân bổ chức danh tiêu biểu: {', '.join(pos_parts)}."
        )
        _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], len(rows), "success", query_type=q_type, effective_scope=effective_scope)
        return _format_response("success", ans, res, None, user.role)

    # Route 0.7: Two-Period Comparison (TC-13: "So sánh tình hình đi muộn của phòng tôi giữa tháng 09/2026 và tháng 10/2026")
    if (
        len(explicit_periods) == 2
        and not period_info["is_range"]
        and any(k in q_lower for k in ["so sánh", "giữa", "so với", "chênh lệch", "thay đổi"])
    ):
        res = compare_periods(
            conn, user, explicit_periods[0], explicit_periods[1],
            department_name=mentioned_dept, target_employee_id=target_emp, force_self=force_self,
        )
        rows = res["rows"]
        if not rows:
            ans = f"Không đủ dữ liệu chấm công để so sánh hai kỳ {explicit_periods[0]} và {explicit_periods[1]}."
            _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "insufficient_data", query_type=q_type, effective_scope=effective_scope)
            return _format_response("insufficient_data", ans, res, None, user.role)

        lines = [
            f"- Kỳ {r['period']}: {r['late_days']} lượt đi muộn / {r['present_days']} ngày đi làm "
            f"(tỷ lệ đi muộn {r['late_rate_pct']}%, đúng giờ {r['on_time_rate_pct']}%, tổng {r['total_work_hours']} giờ công)."
            for r in rows
        ]
        delta_line = ""
        if len(rows) == 2:
            r1, r2 = rows[0], rows[1]
            diff_days = r2["late_days"] - r1["late_days"]
            diff_rate = round(r2["late_rate_pct"] - r1["late_rate_pct"], 2)
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
        chart = {
            "type": "bar",
            "xKey": "period",
            "yKey": "late_rate_pct",
            "label": "Tỷ lệ đi muộn theo kỳ (%)",
            "data": rows,
        }
        _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], len(rows), "success", query_type=q_type, effective_scope=effective_scope)
        return _format_response("success", ans, res, chart, user.role)

    # Strategic Route S1: Multi-month attendance trend (TC-22 & Executive S1)
    if (
        any(k in q_lower for k in ["xu hướng", "nhiều tháng", "theo tháng", "gần đây", "biến động"])
        or bool(re.search(r"\b[2-9]\s*tháng\b|\b1[0-2]\s*tháng\b", q_lower))
        or (period_info["is_range"] and not period_info["is_quarter"] and len(explicit_periods) >= 3)
    ) and any(k in q_lower for k in ["chấm công", "attendance", "đi muộn", "đi làm", "tháng", "tỷ lệ"]):
        m_cnt = re.search(r"(\d+)\s*tháng", q_lower)
        months = int(m_cnt.group(1)) if m_cnt else (len(explicit_periods) if period_info["is_range"] else 3)
        trend_periods = explicit_periods if (period_info["is_range"] and not period_info["is_quarter"]) else None
        res = get_attendance_trend(
            conn, user, months=months, periods=trend_periods,
            department_name=mentioned_dept, force_self=force_self,
        )
        rows = res["rows"]
        if not rows:
            ans = "Không đủ dữ liệu chấm công để tổng hợp xu hướng theo tháng."
            _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "insufficient_data", query_type=q_type, effective_scope=effective_scope)
            return _format_response("insufficient_data", ans, res, None, user.role)

        lines = [
            f"- Kỳ {r['period']}: {r['present_days']} ngày đi làm, {r['late_days']} lượt đi muộn ({r['late_rate_pct']}%), "
            f"đúng giờ {r['on_time_rate_pct']}%, {r['leave_days']} ngày phép, {r['absent_days']} ngày vắng."
            for r in rows
        ]
        summary_tail = ""
        if len(rows) >= 2:
            peak = max(rows, key=lambda x: x["late_rate_pct"])
            low = min(rows, key=lambda x: x["late_rate_pct"])
            delta = round(rows[-1]["late_rate_pct"] - rows[0]["late_rate_pct"], 2)
            sign = "+" if delta > 0 else ""
            summary_tail = (
                f"\nNhận xét xu hướng: Cao nhất tại kỳ {peak['period']} ({peak['late_rate_pct']}%), "
                f"thấp nhất tại kỳ {low['period']} ({low['late_rate_pct']}%), "
                f"biến động từ {rows[0]['period']} đến {rows[-1]['period']} là {sign}{delta} điểm %."
            )
        ans = f"Xu hướng chấm công {len(rows)} tháng trong phạm vi quyền của bạn:\n" + "\n".join(lines) + summary_tail
        chart = {
            "type": "bar",
            "xKey": "period",
            "yKey": "late_rate_pct",
            "label": "Tỷ lệ đi muộn theo tháng (%)",
            "data": rows,
        }
        _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], len(rows), "success", query_type=q_type, effective_scope=effective_scope)
        return _format_response("success", ans, res, chart, user.role)

    # Strategic Route S2: Department ranking by R1-R8 anomalies (TC-24 & Executive S2)
    if (
        any(k in q_lower for k in ["phòng nào", "phòng ban nào", "theo phòng", "nhiều cảnh báo", "mật độ rủi ro"])
        and any(k in q_lower for k in ["cảnh báo", "bất thường", "r1", "r8", "rủi ro"])
    ):
        open_only = "đang mở" in q_lower
        res = get_anomalies_by_department(
            conn, user, period=period, department_name=mentioned_dept, open_only=open_only,
        )
        rows = res["rows"]
        if not rows:
            ans = "Hiện chưa ghi nhận cảnh báo R1-R8 nào trong phạm vi của bạn."
            _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "insufficient_data", query_type=q_type, effective_scope=effective_scope)
            return _format_response("insufficient_data", ans, res, None, user.role)

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
        _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], len(rows), "success", query_type=q_type, effective_scope=effective_scope)
        return _format_response("success", ans, res, chart, user.role)

    # Strategic Route S3: Notable attendance issues ("Những vấn đề attendance nổi bật hiện tại là gì?")
    if any(k in q_lower for k in ["vấn đề", "nổi bật", "tổng quan rủi ro"]) and any(
        k in q_lower for k in ["attendance", "chấm công", "hiện tại", "nổi bật"]
    ):
        res = list_anomalies_tool(
            conn, user, period=period, severity=severity, rule_code=rule_code,
            department_name=mentioned_dept, target_employee_id=target_emp, force_self=force_self,
        )
        rows = res["rows"]
        if not rows:
            ans = "Hiện tại chưa ghi nhận cảnh báo hay vấn đề chấm công nổi bật nào trong phạm vi của bạn."
            _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "insufficient_data", query_type=q_type, effective_scope=effective_scope)
            return _format_response("insufficient_data", ans, res, None, user.role)
        top_lines = [
            f"- [{r['rule_code']} · Mức {r['severity']}] {r['target_code']} ({r['department_name']}, kỳ {r['period']}): {r['explanation']}"
            for r in rows[:5]
        ]
        ans = (
            f"Các vấn đề chấm công nổi bật hiện tại ({len(rows)} cảnh báo R1-R8 trong phạm vi):\n"
            + "\n".join(top_lines)
        )
        _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], len(rows), "success", query_type=q_type, effective_scope=effective_scope)
        return _format_response("success", ans, res, None, user.role)

    # Strategic Route S4: Full Multi-KPI / 2-Department Comparison (TC-21, TC-25 — must precede Route A!)
    is_two_dept_compare = len(mentioned_depts) >= 2 and any(k in q_lower for k in ["so sánh", "giữa", "với", "hiệu suất", "chuyên cần"])
    is_full_exec_compare = (
        any(k in q_lower for k in ["so sánh", "phòng nào", "phòng ban nào", "5 phòng", "các phòng"])
        and (
            any(k in q_lower for k in ["toàn diện", "đúng giờ", "hiệu suất", "chuyên cần"])
            or ("đi muộn" in q_lower and "nghỉ phép" in q_lower)
            or ("cảnh báo" in q_lower and ("đi muộn" in q_lower or "đúng giờ" in q_lower))
        )
    )
    if is_two_dept_compare or is_full_exec_compare:
        filter_depts = mentioned_depts if len(mentioned_depts) >= 2 else None
        res = compare_departments_full(conn, user, period=effective_period, department_names=filter_depts)
        rows = res["rows"]
        if not rows:
            ans = f"Không đủ dữ liệu chấm công cho kỳ {effective_period}."
            _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "insufficient_data", query_type=q_type, effective_scope=effective_scope)
            return _format_response("insufficient_data", ans, res, None, user.role)

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
        chart = {
            "type": "bar",
            "xKey": "department_name",
            "yKey": "late_rate_pct",
            "label": "Tỷ lệ đi muộn (%)",
            "data": rows,
        }
        _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], len(rows), "success", query_type=q_type, effective_scope=effective_scope)
        return _format_response("success", ans, res, chart, user.role)

    # Route A: Anomalies / Cảnh báo bất thường / R1-R8 (supports target_emp, dept, AND TC-17 dual-part high + R8!)
    if any(
        k in q_lower
        for k in [
            "cảnh báo", "bất thường", "thiếu chấm", "quên chấm", "thiếu giờ",
            "trùng giây", "giống hệt", "cuối tuần", "trùng phòng", "gần lễ", "sát lễ",
        ]
    ) or rule_code is not None:
        # TC-17: Dual-part OR query ("cảnh báo mức cao (high) và nhân viên đang vượt quỹ phép năm (R8)")
        is_dual_high_and_r8 = (
            severity == "high"
            and (rule_code == "R8" or "vượt quỹ phép" in q_lower)
            and any(k in q_lower for k in [" và ", " cùng ", " đồng thời "])
        )
        if is_dual_high_and_r8:
            res_high = list_anomalies_tool(
                conn, user, period=period, severity="high",
                department_name=mentioned_dept, target_employee_id=target_emp, force_self=force_self,
            )
            res_r8 = list_anomalies_tool(
                conn, user, period=period, rule_code="R8",
                department_name=mentioned_dept, target_employee_id=target_emp, force_self=force_self,
            )
            seen_ids = set()
            merged_rows: List[Dict[str, Any]] = []
            for r in [*res_high["rows"], *res_r8["rows"]]:
                if r["anomaly_id"] not in seen_ids:
                    seen_ids.add(r["anomaly_id"])
                    merged_rows.append(r)

            combined_res = {
                "tool_name": "list_anomalies",
                "rows": merged_rows,
                "row_count": len(merged_rows),
                "sql_text": f"[1] {res_high['sql_text']} | [2] {res_r8['sql_text']}",
                "execution_ms": round(res_high["execution_ms"] + res_r8["execution_ms"], 2),
            }
            if not merged_rows:
                ans = "Không ghi nhận cảnh báo mức cao hay trường hợp vượt quỹ phép năm (R8) nào trong phạm vi của bạn."
                _log_audit(conn, user, q_clean, "list_anomalies", combined_res["sql_text"], 0, "insufficient_data", query_type=q_type, effective_scope=effective_scope)
                return _format_response("insufficient_data", ans, combined_res, None, user.role)

            sec1 = (
                "\n".join(
                    f"  - [{r['rule_code']} · Mức {r['severity']}] {r['target_code']} ({r['target_name']} – {r['department_name']}, kỳ {r['period']}): {r['explanation']}"
                    for r in res_high["rows"]
                )
                if res_high["rows"] else "  - Không có cảnh báo mức cao."
            )
            sec2 = (
                "\n".join(
                    f"  - [{r['rule_code']} · Mức {r['severity']}] {r['target_code']} ({r['target_name']} – {r['department_name']}, kỳ {r['period']}): {r['explanation']}"
                    for r in res_r8["rows"]
                )
                if res_r8["rows"] else "  - Không có nhân viên vượt quỹ phép năm (R8)."
            )
            ans = (
                f"1. Cảnh báo mức độ cao ({len(res_high['rows'])} bản ghi):\n{sec1}\n\n"
                f"2. Nhân viên vượt quỹ phép năm R8 ({len(res_r8['rows'])} bản ghi):\n{sec2}"
            )
            _log_audit(conn, user, q_clean, "list_anomalies", combined_res["sql_text"], len(merged_rows), "success", query_type=q_type, effective_scope=effective_scope)
            return _format_response("success", ans, combined_res, None, user.role)

        inferred_rule = rule_code
        if not inferred_rule:
            if "thiếu chấm" in q_lower or "quên chấm" in q_lower:
                inferred_rule = "R2"
            elif "thiếu giờ" in q_lower or "dưới 7" in q_lower:
                inferred_rule = "R3"
            elif "gần lễ" in q_lower or "sát lễ" in q_lower:
                inferred_rule = "R4"
            elif "trùng phòng" in q_lower or "cùng nghỉ" in q_lower:
                inferred_rule = "R5"
            elif "trùng giây" in q_lower or "giống hệt" in q_lower:
                inferred_rule = "R6"
            elif "cuối tuần" in q_lower or "thứ bảy" in q_lower:
                inferred_rule = "R7"
            elif "vượt quỹ phép" in q_lower:
                inferred_rule = "R8"

        res = list_anomalies_tool(
            conn, user, period=period, periods=query_periods, severity=severity, rule_code=inferred_rule,
            department_name=mentioned_dept, target_employee_id=target_emp, force_self=force_self,
        )
        rows = res["rows"]
        if not rows:
            # Distinguish existing attendance data (clean 0 anomalies) vs missing period
            avail = get_available_periods(conn)
            if period and period not in avail:
                ans = f"Không đủ dữ liệu cho kỳ {period} trong hệ thống (các kỳ hiện có: {', '.join(avail)})."
                _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "insufficient_data", query_type=q_type, effective_scope=effective_scope)
                return _format_response("insufficient_data", ans, res, None, user.role)
            ans = (
                f"Không đủ dữ liệu hoặc không ghi nhận cảnh báo bất thường nào phù hợp trong phạm vi của bạn"
                f"{f' cho kỳ {period}' if period else ''}."
            )
            _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "insufficient_data", query_type=q_type, effective_scope=effective_scope)
            return _format_response("insufficient_data", ans, res, None, user.role)

        top_lines = [
            f"- [{r['rule_code']} · Mức {r['severity']}] {r['target_code']} ({r['target_name']} – {r['department_name']}, kỳ {r['period']}): {r['explanation']}"
            for r in rows[:8]
        ]
        target_label = f" cho {target_emp}" if target_emp else (f" tại phòng {mentioned_dept}" if mentioned_dept else "")
        ans = (
            f"Tìm thấy {len(rows)} cảnh báo bất thường{target_label} trong phạm vi quyền của bạn"
            f"{f' cho kỳ {period}' if period else ''}:\n" + "\n".join(top_lines)
        )
        _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], len(rows), "success", query_type=q_type, effective_scope=effective_scope)
        return _format_response("success", ans, res, None, user.role)

    # Route B: Leave balance / Quỹ phép còn lại (+ TC-03 combined with pending leave requests + TC-15 Manager self!)
    is_leave_balance_q = (
        "phép" in q_lower
        and any(k in q_lower for k in ["còn bao nhiêu ngày phép", "quỹ phép", "phép còn lại", "ngày phép năm", "vượt quỹ phép"])
    ) or (
        "phép" in q_lower
        and _extract_threshold(q_lower) is not None
        and not any(k in q_lower for k in ["phòng nào", "phòng ban nào"])
    )
    if is_leave_balance_q:
        threshold = _extract_threshold(q_lower)
        if "vượt quỹ" in q_lower:
            threshold = -0.1
        bal_res = get_leave_balance(
            conn, user, threshold=threshold, target_employee_id=target_emp,
            department_name=mentioned_dept, force_self=force_self,
        )
        rows = bal_res["rows"]
        if not rows:
            ans = "Không đủ dữ liệu hoặc không có nhân viên nào thỏa mãn điều kiện quỹ phép trong phạm vi của bạn."
            _log_audit(conn, user, q_clean, bal_res["tool_name"], bal_res["sql_text"], 0, "insufficient_data", query_type=q_type, effective_scope=effective_scope)
            return _format_response("insufficient_data", ans, bal_res, None, user.role)

        if len(rows) == 1:
            r = rows[0]
            rem = float(r["remaining_annual_days"])
            rem_desc = f"còn lại {rem} ngày" if rem >= 0 else f"đang vượt quỹ {abs(rem)} ngày (còn {rem} ngày)"
            bal_text = (
                f"Nhân viên {r['employee_id']} ({r['full_name']} – Phòng {r['department_name']}) có quỹ phép năm "
                f"{r['annual_leave_balance']} ngày, đã duyệt {r['used_annual_days']} ngày (tính theo ngày lịch), {rem_desc}."
            )
        else:
            lines = [
                f"- {r['employee_id']} ({r['full_name']} – {r['department_name']}): đã dùng {r['used_annual_days']}/{r['annual_leave_balance']} ngày (còn {r['remaining_annual_days']} ngày)"
                for r in rows[:8]
            ]
            bal_text = f"Danh sách quỹ phép năm ({len(rows)} nhân viên trong phạm vi):\n" + "\n".join(lines)

        # TC-03: Also asked about pending leave requests in the same question?
        if any(k in q_lower for k in ["chờ duyệt", "đang chờ", "đơn nghỉ phép nào", "đơn nào"]):
            pend_res = list_leave_requests_detail(
                conn, user, status_filter="pending", target_employee_id=target_emp,
                department_name=mentioned_dept, force_self=force_self,
            )
            p_rows = pend_res["rows"]
            if p_rows:
                p_lines = [
                    f"  - Đơn #{p['request_id']} ({LEAVE_TYPE_LABELS.get(p['leave_type'], p['leave_type'])}): "
                    f"từ {p['from_date']} đến {p['to_date']} ({p['leave_days']} ngày) — Trạng thái: Chờ duyệt ({p['reason']})"
                    for p in p_rows[:8]
                ]
                pend_text = f"Đơn nghỉ phép đang chờ duyệt ({len(p_rows)} đơn):\n" + "\n".join(p_lines)
            else:
                pend_text = "Hiện tại bạn không có đơn nghỉ phép nào đang chờ duyệt."

            combined_res = {
                "tool_name": "get_leave_balance+list_leave_requests_detail",
                "rows": p_rows if p_rows else rows,
                "row_count": len(rows) + len(p_rows),
                "sql_text": f"[1] {bal_res['sql_text']} | [2] {pend_res['sql_text']}",
                "execution_ms": round(bal_res["execution_ms"] + pend_res["execution_ms"], 2),
            }
            ans = f"1. Quỹ phép năm:\n{bal_text}\n\n2. Trạng thái đơn chờ duyệt:\n{pend_text}"
            _log_audit(conn, user, q_clean, combined_res["tool_name"], combined_res["sql_text"], combined_res["row_count"], "success", query_type=q_type, effective_scope=effective_scope)
            return _format_response("success", ans, combined_res, None, user.role)

        _log_audit(conn, user, q_clean, bal_res["tool_name"], bal_res["sql_text"], len(rows), "success", query_type=q_type, effective_scope=effective_scope)
        return _format_response("success", bal_text, bal_res, None, user.role)

    # Route C: Standard single-metric department late comparison ("Phòng ban nào có tỷ lệ đi muộn cao nhất?")
    if any(k in q_lower for k in ["phòng nào", "phòng ban nào", "so sánh", "theo phòng ban", "các phòng"]) and "nghỉ phép" not in q_lower:
        res = compare_department_metrics(conn, user, period=effective_period)
        rows = res["rows"]
        if not rows:
            ans = f"Không đủ dữ liệu chấm công cho kỳ {effective_period}."
            _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "insufficient_data", query_type=q_type, effective_scope=effective_scope)
            return _format_response("insufficient_data", ans, res, None, user.role)

        top = rows[0]
        ans = (
            f"Theo dữ liệu chấm công kỳ {effective_period}, phòng {top['department_name']} có tỷ lệ đi muộn cao nhất "
            f"với {top['late_rate_pct']}% ({top['late_days']} lượt đi muộn / {top['present_days']} ngày đi làm, "
            f"tỷ lệ đúng giờ {top['on_time_rate_pct']}%, tổng {top['total_work_hours']} giờ công)."
        )
        chart = {
            "type": "bar",
            "xKey": "department_name",
            "yKey": "late_rate_pct",
            "label": "Tỷ lệ đi muộn (%)",
            "data": rows,
        }
        _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], len(rows), "success", query_type=q_type, effective_scope=effective_scope)
        return _format_response("success", ans, res, chart, user.role)

    # Route D: Leave requests — Detailed queue (TC-12 pending, TC-23 executive approval) vs Dept statistics (TC-19)
    if any(k in q_lower for k in ["nghỉ phép", "đơn nghỉ", "đơn phép", "chờ ban điều hành", "phê duyệt cấp cao"]):
        leave_status = _extract_leave_status(q_lower)
        exec_approval_only = any(
            k in q_lower for k in ["ban điều hành", "cấp cao", "đặc biệt", "lãnh đạo phê duyệt", "requires_executive_approval"]
        )
        wants_detail_list = (
            exec_approval_only
            or leave_status is not None
            or any(k in q_lower for k in ["những đơn nào", "danh sách đơn", "đơn nào đang", "chi tiết đơn"])
            or target_emp is not None
        )
        if wants_detail_list:
            res = list_leave_requests_detail(
                conn,
                user,
                period=period,
                status_filter=leave_status or ("pending" if exec_approval_only else None),
                department_name=mentioned_dept,
                target_employee_id=target_emp,
                requires_executive_approval=True if exec_approval_only else None,
                force_self=force_self,
            )
            rows = res["rows"]
            if not rows:
                ans = (
                    "Hiện không có đơn nghỉ phép đặc biệt nào đang chờ Ban Điều hành phê duyệt."
                    if exec_approval_only
                    else f"Không ghi nhận đơn nghỉ phép nào phù hợp trong phạm vi quyền của bạn{f' cho kỳ {period}' if period else ''}."
                )
                _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "insufficient_data", query_type=q_type, effective_scope=effective_scope)
                return _format_response("insufficient_data", ans, res, None, user.role)

            lines = [
                f"- Đơn #{r['request_id']} | {r['employee_id']} ({r['full_name']} – Phòng {r['department_name']}): "
                f"{LEAVE_TYPE_LABELS.get(r['leave_type'], r['leave_type'])}, từ {r['from_date']} đến {r['to_date']} "
                f"({r['leave_days']} ngày) · {LEAVE_STATUS_LABELS.get(r['status'], r['status'])} — Lý do: {r['reason']}"
                for r in rows[:10]
            ]
            title = (
                f"Danh sách đơn nghỉ phép đặc biệt đang chờ Ban Điều hành phê duyệt ({len(rows)} đơn):"
                if exec_approval_only
                else f"Danh sách đơn nghỉ phép ({len(rows)} đơn trong phạm vi quyền của bạn):"
            )
            ans = f"{title}\n" + "\n".join(lines)
            _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], len(rows), "success", query_type=q_type, effective_scope=effective_scope)
            return _format_response("success", ans, res, None, user.role)

        # Department leave statistics (now properly filtered by mentioned_dept — TC-19!)
        res = get_leave_by_department(
            conn, user, period=period, department_name=mentioned_dept,
            target_employee_id=target_emp, force_self=force_self,
        )
        rows = res["rows"]
        if not rows:
            ans = f"Không đủ dữ liệu đơn nghỉ phép trong phạm vi của bạn{f' tại phòng {mentioned_dept}' if mentioned_dept else ''}{f' cho kỳ {period}' if period else ''}."
            _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "insufficient_data", query_type=q_type, effective_scope=effective_scope)
            return _format_response("insufficient_data", ans, res, None, user.role)

        lines = [
            f"- Phòng {r['department_name']}: {r['total_requests']} đơn ({r['approved_requests']} đã duyệt, "
            f"{r['pending_requests']} chờ duyệt, {r['rejected_requests']} từ chối; tổng {r['approved_leave_days']} ngày phép đã duyệt)"
            for r in rows
        ]
        ans = f"Thống kê nghỉ phép{f' phòng {mentioned_dept}' if mentioned_dept else ''}{f' kỳ {period}' if period else ''} trong phạm vi của bạn:\n" + "\n".join(lines)
        chart = (
            {
                "type": "bar",
                "xKey": "department_name",
                "yKey": "approved_leave_days",
                "label": "Số ngày nghỉ phép đã duyệt",
                "data": rows,
            }
            if len(rows) > 1 else None
        )
        _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], len(rows), "success", query_type=q_type, effective_scope=effective_scope)
        return _format_response("success", ans, res, chart, user.role)

    # Route E: Late attendance — Specific late dates / Top N personal late days (TC-01, TC-05) / Employee late + hours (TC-16) / Zero late vs missing (TC-04) / Top late employees
    if any(k in q_lower for k in ["đi muộn", "trễ", "muộn nhiều nhất"]):
        wants_specific_dates = any(
            k in q_lower for k in ["ngày nào", "những ngày nào", "chi tiết ngày", "cụ thể vào những ngày", "những ngày đi muộn"]
        )
        wants_top_personal_days = (
            "top " in q_lower
            and (force_self or target_emp is not None)
            and any(k in q_lower for k in ["ngày", "lần"])
            and not any(k in q_lower for k in ["nhân viên", "người"])
        )
        if wants_specific_dates or wants_top_personal_days:
            detail_limit = _extract_limit(q_lower, default=31) if wants_top_personal_days else 31
            order_by = "late_minutes_desc" if (wants_top_personal_days or "nhiều phút nhất" in q_lower) else "date"
            res = get_employee_attendance_detail(
                conn,
                user,
                period=None if query_periods else effective_period,
                periods=query_periods,
                target_employee_id=target_emp,
                department_name=mentioned_dept,
                filter_type="late",
                order_by=order_by,
                limit=detail_limit,
                force_self=force_self,
            )
            rows = res["rows"]
            if not rows:
                if res.get("has_attendance_data"):
                    ans = (
                        f"Kỳ {effective_period} có {res['present_days_in_scope']} ngày đi làm trong phạm vi tra cứu "
                        "và ghi nhận **0 lần đi muộn**."
                    )
                    _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "success", query_type=q_type, effective_scope=effective_scope)
                    return _format_response("success", ans, res, None, user.role)
                ans = f"Không đủ dữ liệu chấm công cho kỳ {effective_period} trong phạm vi của bạn."
                _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "insufficient_data", query_type=q_type, effective_scope=effective_scope)
                return _format_response("insufficient_data", ans, res, None, user.role)

            total_mins = sum(int(r.get("late_minutes") or 0) for r in rows)
            first_emp = f"{rows[0]['employee_id']} ({rows[0]['full_name']})"
            day_lines = [
                f"- {r['work_date']}: vào lúc {r['check_in']} (muộn {r['late_minutes']} phút, {r['work_hours']} giờ công)"
                for r in rows
            ]
            if wants_top_personal_days:
                ans = (
                    f"Top {len(rows)} ngày đi muộn nhiều phút nhất của {first_emp} trong kỳ {effective_period}:\n"
                    + "\n".join(day_lines)
                )
            else:
                ans = (
                    f"Trong kỳ {effective_period}, nhân viên {first_emp} đi muộn **{len(rows)} lần** "
                    f"(tổng {total_mins} phút), cụ thể vào các ngày:\n" + "\n".join(day_lines)
                )
            _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], len(rows), "success", query_type=q_type, effective_scope=effective_scope)
            return _format_response("success", ans, res, None, user.role)

        # TC-16: Specific employee asked for BOTH late count AND total work hours!
        if (target_emp is not None or force_self) and any(k in q_lower for k in ["giờ công", "tổng giờ", "tổng hợp"]):
            sum_res = get_attendance_summary(
                conn, user, period=None if query_periods else effective_period, periods=query_periods,
                department_name=mentioned_dept, target_employee_id=target_emp, force_self=force_self,
            )
            late_res = get_top_late_employees(
                conn, user, period=None if query_periods else effective_period, periods=query_periods,
                limit=5, department_name=mentioned_dept, target_employee_id=target_emp, force_self=force_self,
            )
            if not sum_res["rows"]:
                ans = f"Không đủ dữ liệu chấm công cho kỳ {effective_period} trong phạm vi tra cứu."
                _log_audit(conn, user, q_clean, sum_res["tool_name"], sum_res["sql_text"], 0, "insufficient_data", query_type=q_type, effective_scope=effective_scope)
                return _format_response("insufficient_data", ans, sum_res, None, user.role)

            sr = sum_res["rows"][0]
            emp_label = target_emp or user.employee_id
            if late_res["rows"]:
                lr = late_res["rows"][0]
                emp_label = f"{lr['employee_id']} ({lr['full_name']} – Phòng {lr['department_name']})"
                late_detail = f"{lr['late_days']} lần đi muộn (tổng {lr['total_late_minutes']} phút, trung bình {lr['avg_late_minutes']} phút/lần)"
            else:
                late_detail = "0 lần đi muộn"

            combined_res = {
                "tool_name": "get_attendance_summary+get_top_late_employees",
                "rows": sum_res["rows"],
                "row_count": len(sum_res["rows"]),
                "sql_text": f"[1] {sum_res['sql_text']} | [2] {late_res['sql_text']}",
                "execution_ms": round(sum_res["execution_ms"] + late_res["execution_ms"], 2),
            }
            ans = (
                f"Kỳ {sr['period']}, nhân viên {emp_label} ghi nhận {late_detail}, "
                f"tổng **{sr['total_work_hours']} giờ công** trên {sr['present_days']} ngày đi làm "
                f"(tỷ lệ đúng giờ {sr['on_time_rate_pct']}%, tỷ lệ đi muộn {sr['late_rate_pct']}%)."
            )
            _log_audit(conn, user, q_clean, combined_res["tool_name"], combined_res["sql_text"], len(sum_res["rows"]), "success", query_type=q_type, effective_scope=effective_scope)
            return _format_response("success", ans, combined_res, None, user.role)

        # Standard late count / Top late employees (now passes target_emp & handles 0 late days cleanly!)
        asking_total_count = any(k in q_lower for k in ["bao nhiêu người", "mấy người", "có bao nhiêu nhân viên"])
        limit = _extract_limit(q_lower, default=50 if asking_total_count else 5)
        res = get_top_late_employees(
            conn,
            user,
            period=None if query_periods else effective_period,
            periods=query_periods,
            limit=limit,
            department_name=mentioned_dept,
            target_employee_id=target_emp,
            force_self=force_self,
        )
        rows = res["rows"]
        period_label = period_info["quarter_label"] or effective_period
        if not rows:
            # TC-04: Distinguish 0 late days (with valid attendance records!) from missing period data
            if res.get("has_attendance_data"):
                who = f"nhân viên {target_emp}" if target_emp else (
                    f"nhân viên {user.employee_id} ({user.full_name})" if force_self else "trong phạm vi tra cứu"
                )
                ans = (
                    f"Trong kỳ {period_label}, {who} có {res['present_days_in_scope']} ngày đi làm "
                    f"và ghi nhận **0 lần đi muộn** (đi làm đúng giờ 100%)."
                )
                _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "success", query_type=q_type, effective_scope=effective_scope)
                return _format_response("success", ans, res, None, user.role)

            ans = f"Không đủ dữ liệu hoặc không ghi nhận lượt đi muộn nào trong kỳ {period_label}."
            _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "insufficient_data", query_type=q_type, effective_scope=effective_scope)
            return _format_response("insufficient_data", ans, res, None, user.role)

        if force_self or target_emp is not None or (len(rows) == 1 and not asking_total_count):
            r = rows[0]
            ans = (
                f"Nhân viên {r['employee_id']} ({r['full_name']} – Phòng {r['department_name']}) đi muộn "
                f"{r['late_days']} lần trong kỳ {period_label} "
                f"(tổng {r['total_late_minutes']} phút, trung bình {r['avg_late_minutes']} phút/lần)."
            )
        else:
            lines = [
                f"{i}. {r['employee_id']} ({r['full_name']} – {r['department_name']}): {r['late_days']} lần đi muộn (tổng {r['total_late_minutes']} phút)"
                for i, r in enumerate(rows[:10], start=1)
            ]
            prefix = (
                f"Có {len(rows)} nhân viên ghi nhận đi muộn"
                if asking_total_count
                else f"Danh sách {len(rows)} nhân viên đi muộn nhiều nhất"
            )
            extra = f"\n(Hiển thị 10/{len(rows)} người đi muộn nhiều nhất; xem đầy đủ trong bảng dữ liệu.)" if len(rows) > 10 else ""
            ans = f"{prefix} kỳ {period_label}:\n" + "\n".join(lines) + extra
        _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], len(rows), "success", query_type=q_type, effective_scope=effective_scope)
        return _format_response("success", ans, res, None, user.role)

    # Route H: Public holidays & Overtime requests
    if any(k in q_lower for k in ["ngày lễ", "tăng ca", "overtime", "làm thêm giờ"]):
        res = list_holidays_and_overtime(
            conn, user, period=period, target_employee_id=target_emp,
            department_name=mentioned_dept, force_self=force_self,
        )
        hols = res.get("holidays") or []
        ot_rows = res["rows"]
        hol_text = ", ".join(f"{h['holiday_date']} ({h['name']})" for h in hols) if hols else "chưa có dữ liệu"
        if "tăng ca" in q_lower or "overtime" in q_lower or "làm thêm" in q_lower:
            ot_text = (
                "\n".join(f"- {r['employee_id']} ({r['full_name']}) ngày {r['work_date']}: {r['status']}" for r in ot_rows[:10])
                if ot_rows else "Chưa ghi nhận đơn tăng ca nào trong phạm vi quyền của bạn."
            )
            ans = f"Đơn làm thêm giờ (OT) trong phạm vi của bạn ({len(ot_rows)} bản ghi):\n{ot_text}\nNgày lễ công ty: {hol_text}."
        else:
            ans = f"Danh sách ngày lễ công ty đã cấu hình ({len(hols)} ngày): {hol_text}."
        _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], len(ot_rows), "success", query_type=q_type, effective_scope=effective_scope)
        return _format_response("success", ans, res, None, user.role)

    # Route F: Default Attendance Summary (now respects target_emp, periods/quarter, force_self & canonical rates!)
    res = get_attendance_summary(
        conn,
        user,
        period=None if query_periods else effective_period,
        periods=query_periods,
        department_name=mentioned_dept,
        target_employee_id=target_emp,
        force_self=force_self,
    )
    rows = res["rows"]
    if not rows:
        avail = get_available_periods(conn)
        hint = f" (Các kỳ hiện có dữ liệu: {', '.join(avail)})." if avail else "."
        ans = f"Không đủ dữ liệu chấm công cho kỳ {period_info['quarter_label'] or effective_period} trong phạm vi của bạn{hint}"
        _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "insufficient_data", query_type=q_type, effective_scope=effective_scope)
        return _format_response("insufficient_data", ans, res, None, user.role)

    r = rows[0]
    target_prefix = f"Nhân viên {target_emp} — " if target_emp else (f"Phòng {mentioned_dept} — " if mentioned_dept else "")
    ans = (
        f"{target_prefix}Tổng hợp chấm công kỳ {r['period']} ({r['employee_count']} nhân sự trong phạm vi): "
        f"tổng {r['total_work_hours']} giờ công, {r['present_days']} ngày đi làm "
        f"(tỷ lệ đúng giờ {r['on_time_rate_pct']}%), {r['late_days']} lượt đi muộn (tỷ lệ {r['late_rate_pct']}%), "
        f"{r['missing_punch_days']} lượt thiếu chấm công, {r['leave_days']} ngày nghỉ phép ({r['leave_rate_pct']}%) "
        f"và {r['absent_days']} ngày vắng."
    )
    _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], len(rows), "success", query_type=q_type, effective_scope=effective_scope)
    return _format_response("success", ans, res, None, user.role)


def _format_response(
    status: str,
    answer: str,
    tool_result: Dict[str, Any],
    chart: Optional[Dict[str, Any]],
    role: RoleEnum,
) -> Dict[str, Any]:
    rows = tool_result.get("rows") or []
    table = None
    if rows:
        table = {
            "columns": list(rows[0].keys()),
            "rows": rows,
        }
    return {
        "status": status,
        "answer": answer,
        "table": table,
        "chart": chart,
        "trace": {
            "tool_name": tool_result.get("tool_name"),
            "sql_text": tool_result.get("sql_text"),
            "row_count": tool_result.get("row_count", 0),
            "execution_ms": tool_result.get("execution_ms", 0.0),
        },
        "suggested_followups": get_suggested_prompts(role),
    }
