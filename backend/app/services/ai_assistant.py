from __future__ import annotations

import re
import sqlite3
from typing import Any, Dict, List, Optional

from app.core.security import AuthenticatedUser
from app.schemas.common import RoleEnum
from app.services.ai_tools import (
    compare_department_metrics,
    get_anomalies_by_department,
    get_attendance_summary,
    get_attendance_trend,
    get_leave_balance,
    get_leave_by_department,
    get_top_late_employees,
    list_anomalies_tool,
)

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
    r"\bmật\s*khẩu\b",
    r"\bpassword\b",
    r"\bbảng\s+users\b",
    r"system\s*prompt",
    r"bypass\s+rbac",
    r"show\s+all\s+tables",
    r"sqlite_master",
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

DEPARTMENT_ALIASES: Dict[str, str] = {
    "kinh doanh": "Kinh doanh",
    "sales": "Kinh doanh",
    "kỹ thuật": "Kỹ thuật",
    "ky thuat": "Kỹ thuật",
    "tech": "Kỹ thuật",
    "nhân sự": "Nhân sự",
    "nhan su": "Nhân sự",
    "hr": "Nhân sự",
    "marketing": "Marketing",
    "mkt": "Marketing",
    "vận hành": "Vận hành",
    "van hanh": "Vận hành",
    "ops": "Vận hành",
}


def get_suggested_prompts(role: RoleEnum) -> List[str]:
    if role == RoleEnum.employee:
        return [
            "Tháng 10/2026 tôi đi muộn bao nhiêu lần?",
            "Tôi còn bao nhiêu ngày phép năm?",
            "Tổng hợp chấm công của tôi tháng 10/2026",
            "Tôi có cảnh báo bất thường nào không?",
        ]
    if role == RoleEnum.manager:
        return [
            "Tổng hợp chấm công phòng tôi tháng 10/2026",
            "Top 5 nhân viên đi muộn nhiều nhất phòng tôi tháng 10/2026",
            "Phòng tôi có cảnh báo bất thường nào tháng 10/2026?",
            "Ai còn dưới 10 ngày phép năm trong phòng tôi?",
        ]
    if role == RoleEnum.executive:
        return [
            "Phòng ban nào có tỷ lệ đi muộn cao nhất?",
            "Xu hướng chấm công 3 tháng gần đây thế nào?",
            "Phòng nào có nhiều cảnh báo R1-R8 nhất?",
            "Những vấn đề attendance nổi bật hiện tại là gì?",
        ]
    if role == RoleEnum.admin:
        return []
    return [
        "Phòng nào có tỷ lệ đi muộn cao nhất tháng 10/2026?",
        "Liệt kê top 5 nhân viên đi muộn nhiều nhất tháng 10/2026",
        "Thống kê nghỉ phép theo phòng ban tháng 10/2026",
        "Liệt kê các cảnh báo bất thường mức cao",
        "Ai đang vượt quỹ phép năm hoặc còn dưới 5 ngày phép?",
    ]


def _extract_period(q_lower: str) -> Optional[str]:
    # Matches YYYY-MM
    m_iso = re.search(r"\b(20\d{2})[-/](0?[1-9]|1[0-2])\b", q_lower)
    if m_iso:
        return f"{m_iso.group(1)}-{int(m_iso.group(2)):02d}"

    # Matches "tháng 10/2026" or "tháng 10 năm 2026"
    m_vn_full = re.search(r"tháng\s*(0?[1-9]|1[0-2])\s*(?:/|năm\s*)(20\d{2})", q_lower)
    if m_vn_full:
        return f"{m_vn_full.group(2)}-{int(m_vn_full.group(1)):02d}"

    # Matches "tháng 10" -> defaults to 2026
    m_vn_month = re.search(r"tháng\s*(0?[1-9]|1[0-2])\b", q_lower)
    if m_vn_month:
        return f"2026-{int(m_vn_month.group(1)):02d}"

    if "tháng này" in q_lower or "kỳ này" in q_lower:
        return "2026-10"
    if "tháng trước" in q_lower:
        return "2026-09"
    return None


def _extract_employee_codes(question: str) -> List[str]:
    return [m.upper() for m in re.findall(r"\bNV\d{3}\b", question, flags=re.IGNORECASE)]


def _extract_department_mention(q_lower: str) -> Optional[str]:
    for alias, canonical in DEPARTMENT_ALIASES.items():
        if re.search(rf"phòng\s+{re.escape(alias)}\b", q_lower) or re.search(rf"khối\s+{re.escape(alias)}\b", q_lower):
            return canonical
    return None


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


def _extract_rule_code(question: str) -> Optional[str]:
    m = re.search(r"\b(R[1-8])\b", question, flags=re.IGNORECASE)
    return m.group(1).upper() if m else None


def _role_scope_label(role: RoleEnum) -> str:
    if role in (RoleEnum.hr, RoleEnum.executive):
        return "all"
    if role == RoleEnum.manager:
        return "department"
    if role == RoleEnum.admin:
        return "system"
    return "self"


def _log_audit(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    question: str,
    tool_name: Optional[str],
    sql_text: Optional[str],
    row_count: int,
    status: str,
    query_type: Optional[str] = None,
) -> None:
    db_status = status if status in ("success", "blocked", "error", "insufficient_data") else "success"
    scope = _role_scope_label(user.role)
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


def answer_question(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    question: str,
) -> Dict[str, Any]:
    q_clean = question.strip()
    q_lower = q_clean.lower()

    # 0. Strict RBAC permission guard inside AI Orchestrator (defense-in-depth: Admin has NO HR AI access by default)
    if user.role == RoleEnum.admin or not user.has_any_permission(
        "ai.ask.self", "ai.ask.department", "ai.ask.all", "ai.strategy"
    ):
        answer = (
            "Vai trò Quản trị hệ thống (Admin) không mặc định được cấp quyền truy vấn dữ liệu nghiệp vụ nhân sự qua Trợ lý AI."
        )
        _log_audit(conn, user, q_clean, "rbac_guard", None, 0, "blocked", query_type="rbac_block")
        return {
            "status": "blocked",
            "answer": answer,
            "table": None,
            "chart": None,
            "trace": {"tool_name": "rbac_guard", "sql_text": None, "row_count": 0, "execution_ms": 0.0},
            "suggested_followups": [],
        }

    # 1. Prompt Injection / Security Attack Guard
    for pattern in PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, q_lower):
            answer = (
                "Yêu cầu bị từ chối bởi lớp bảo mật hệ thống. Trợ lý AI chỉ hỗ trợ truy vấn đọc "
                "dữ liệu chấm công và nghỉ phép trong đúng phạm vi quyền hạn của tài khoản."
            )
            _log_audit(conn, user, q_clean, "security_guard", None, 0, "blocked")
            return {
                "status": "blocked",
                "answer": answer,
                "table": None,
                "chart": None,
                "trace": {"tool_name": "security_guard", "sql_text": None, "row_count": 0, "execution_ms": 0.0},
                "suggested_followups": get_suggested_prompts(user.role),
            }

    # 2. Out-of-scope Guard (Payroll / Salary / Recruitment)
    for pattern in OUT_OF_SCOPE_PATTERNS:
        if re.search(pattern, q_lower):
            answer = (
                "Hệ thống HR Attendance Copilot chỉ quản lý dữ liệu chấm công, đơn nghỉ phép và cảnh báo bất thường; "
                "hệ thống không lưu trữ dữ liệu tiền lương, thuế hay tuyển dụng."
            )
            _log_audit(conn, user, q_clean, "scope_policy_guard", None, 0, "blocked")
            return {
                "status": "blocked",
                "answer": answer,
                "table": None,
                "chart": None,
                "trace": {"tool_name": "scope_policy_guard", "sql_text": None, "row_count": 0, "execution_ms": 0.0},
                "suggested_followups": get_suggested_prompts(user.role),
            }

    # 3. Cross-role RBAC intent checks (prevent guessing or misleading scope responses)
    emp_codes = _extract_employee_codes(q_clean)
    mentioned_dept = _extract_department_mention(q_lower)

    if user.role == RoleEnum.employee:
        other_emps = [e for e in emp_codes if e != user.employee_id]
        if other_emps:
            answer = (
                f"Bạn đang đăng nhập với vai trò Nhân viên ({user.employee_id}) nên chỉ được phép tra cứu dữ liệu "
                f"của chính mình, không có quyền xem dữ liệu của nhân viên {', '.join(other_emps)}."
            )
            _log_audit(conn, user, q_clean, "rbac_guard", None, 0, "blocked")
            return {
                "status": "blocked",
                "answer": answer,
                "table": None,
                "chart": None,
                "trace": {"tool_name": "rbac_guard", "sql_text": None, "row_count": 0, "execution_ms": 0.0},
                "suggested_followups": get_suggested_prompts(user.role),
            }
        if any(k in q_lower for k in ["phòng nào", "phòng ban nào", "toàn công ty", "các phòng", "so sánh phòng", "top "]) or (
            mentioned_dept is not None
        ):
            answer = (
                f"Vai trò Nhân viên ({user.employee_id}) chỉ xem được dữ liệu cá nhân, không có quyền xem thống kê "
                "cấp phòng ban hoặc so sánh toàn công ty."
            )
            _log_audit(conn, user, q_clean, "rbac_guard", None, 0, "blocked")
            return {
                "status": "blocked",
                "answer": answer,
                "table": None,
                "chart": None,
                "trace": {"tool_name": "rbac_guard", "sql_text": None, "row_count": 0, "execution_ms": 0.0},
                "suggested_followups": get_suggested_prompts(user.role),
            }

    if user.role == RoleEnum.manager:
        if mentioned_dept and mentioned_dept.lower() != user.department_name.lower():
            answer = (
                f"Bạn đang đăng nhập với vai trò Trưởng phòng {user.department_name}, "
                f"không có quyền tra cứu dữ liệu của phòng {mentioned_dept}."
            )
            _log_audit(conn, user, q_clean, "rbac_guard", None, 0, "blocked")
            return {
                "status": "blocked",
                "answer": answer,
                "table": None,
                "chart": None,
                "trace": {"tool_name": "rbac_guard", "sql_text": None, "row_count": 0, "execution_ms": 0.0},
                "suggested_followups": get_suggested_prompts(user.role),
            }
        if any(k in q_lower for k in ["toàn công ty", "phòng nào", "phòng ban nào", "so sánh các phòng", "phòng khác"]):
            answer = (
                f"Vai trò Trưởng phòng {user.department_name} chỉ được phép tra cứu số liệu trong phạm vi "
                f"phòng {user.department_name}, không được xem dữ liệu toàn công ty hoặc so sánh phòng ban khác."
            )
            _log_audit(conn, user, q_clean, "rbac_guard", None, 0, "blocked")
            return {
                "status": "blocked",
                "answer": answer,
                "table": None,
                "chart": None,
                "trace": {"tool_name": "rbac_guard", "sql_text": None, "row_count": 0, "execution_ms": 0.0},
                "suggested_followups": get_suggested_prompts(user.role),
            }
        if emp_codes:
            for code in emp_codes:
                row_emp = conn.execute(
                    "SELECT department_id FROM employees WHERE employee_id = ?",
                    (code,),
                ).fetchone()
                if row_emp is None or row_emp["department_id"] != user.department_id:
                    answer = (
                        f"Nhân viên {code} không thuộc phòng {user.department_name} mà bạn quản lý "
                        "(hoặc không tồn tại trong phạm vi của bạn), nên hệ thống từ chối cung cấp dữ liệu."
                    )
                    _log_audit(conn, user, q_clean, "rbac_guard", None, 0, "blocked")
                    return {
                        "status": "blocked",
                        "answer": answer,
                        "table": None,
                        "chart": None,
                        "trace": {"tool_name": "rbac_guard", "sql_text": None, "row_count": 0, "execution_ms": 0.0},
                        "suggested_followups": get_suggested_prompts(user.role),
                    }

    # 4. Ambiguous / too-short / generic domain-only question check -> ask clarifying question (no SQL executed)
    domain_keywords = [
        "đi muộn", "trễ", "chấm công", "attendance", "giờ công", "nghỉ phép", "phép", "quỹ phép",
        "cảnh báo", "bất thường", "thiếu chấm", "quên chấm", "cuối tuần", "trùng",
        "r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "so sánh", "phòng ban", "phòng nào",
        "nv0", "tổng hợp", "chuyên cần", "thống kê tháng", "xu hướng", "nổi bật", "3 tháng",
    ]
    generic_ambiguous_queries = {
        "chấm công", "nghỉ phép", "cảnh báo", "báo cáo", "bất thường",
        "đi muộn", "phép năm", "nhân sự", "thống kê", "tổng hợp",
        "xem chấm công", "xem nghỉ phép", "xem cảnh báo", "xem báo cáo",
    }
    period = _extract_period(q_lower)
    severity = _extract_severity(q_lower)
    rule_code = _extract_rule_code(q_clean)
    q_norm = re.sub(r"[?!.,:;]+$", "", q_lower).strip()
    words = [w for w in q_norm.split() if w]

    is_generic_short = (
        q_norm in generic_ambiguous_queries
        or (len(words) <= 2 and not emp_codes and not rule_code and not period and not severity)
    )
    if len(q_clean) < 8 or not any(k in q_lower for k in domain_keywords) or is_generic_short:
        answer = (
            "Câu hỏi của bạn hơi chung chung nên tôi chưa xác định rõ chỉ số cần tra cứu. "
            "Bạn vui lòng nêu cụ thể hơn về nội dung (đi muộn, quỹ phép năm, cảnh báo bất thường, hay tổng hợp chấm công) "
            "và thời gian (ví dụ: tháng 10/2026) nhé."
        )
        _log_audit(conn, user, q_clean, "clarification", None, 0, "success")
        return {
            "status": "clarification_needed",
            "clarification_needed": True,
            "answer": answer,
            "table": None,
            "chart": None,
            "trace": {"tool_name": "clarification", "sql_text": None, "row_count": 0, "execution_ms": 0.0},
            "suggested_followups": get_suggested_prompts(user.role),
        }

    effective_period = period or "2026-10"
    target_emp = emp_codes[0] if emp_codes else None

    # 5. Deterministic Function Calling Routing (SQL computes 100% of numbers!)
    q_type = "ai_strategy" if user.role == RoleEnum.executive else "ai_sql"

    # Strategic Route S1: Multi-month attendance trend (e.g. "Xu hướng chấm công 3 tháng gần đây thế nào?")
    if any(k in q_lower for k in ["xu hướng", "3 tháng", "nhiều tháng", "theo tháng", "gần đây"]) and any(
        k in q_lower for k in ["chấm công", "attendance", "đi muộn", "đi làm", "tháng"]
    ):
        m_cnt = re.search(r"(\d+)\s*tháng", q_lower)
        months = int(m_cnt.group(1)) if m_cnt else 3
        res = get_attendance_trend(conn, user, months=months)
        rows = res["rows"]
        if not rows:
            ans = "Không đủ dữ liệu chấm công để tổng hợp xu hướng theo tháng."
            _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "insufficient_data", query_type=q_type)
            return _format_response("insufficient_data", ans, res, None, user.role)

        lines = [
            f"- Kỳ {r['period']}: {r['present_days']} ngày đi làm, {r['late_days']} lượt đi muộn ({r['late_rate_pct']}%), "
            f"{r['leave_days']} ngày phép, {r['absent_days']} ngày vắng."
            for r in rows
        ]
        ans = f"Xu hướng chấm công {len(rows)} tháng gần nhất trong phạm vi quyền của bạn:\n" + "\n".join(lines)
        chart = {
            "type": "bar",
            "xKey": "period",
            "yKey": "late_rate_pct",
            "label": "Tỷ lệ đi muộn theo tháng (%)",
            "data": rows,
        }
        _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], len(rows), "success", query_type=q_type)
        return _format_response("success", ans, res, chart, user.role)

    # Strategic Route S2: Department ranking by R1-R8 anomalies ("Phòng nào có nhiều cảnh báo R1-R8 nhất?")
    if (
        any(k in q_lower for k in ["phòng nào", "phòng ban nào", "theo phòng", "nhiều cảnh báo"])
        and any(k in q_lower for k in ["cảnh báo", "bất thường", "r1", "r8"])
    ):
        res = get_anomalies_by_department(conn, user, period=period)
        rows = res["rows"]
        if not rows:
            ans = "Hiện chưa ghi nhận cảnh báo R1-R8 nào trong phạm vi của bạn."
            _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "insufficient_data", query_type=q_type)
            return _format_response("insufficient_data", ans, res, None, user.role)

        top = rows[0]
        lines = [
            f"- Phòng {r['department_name']}: {r['total_anomalies']} cảnh báo ({r['open_anomalies']} đang mở, {r['high_anomalies']} mức cao)"
            for r in rows
        ]
        ans = (
            f"Phòng {top['department_name']} hiện có nhiều cảnh báo R1-R8 nhất với {top['total_anomalies']} cảnh báo "
            f"({top['open_anomalies']} đang mở, {top['high_anomalies']} mức cao):\n" + "\n".join(lines)
        )
        chart = {
            "type": "bar",
            "xKey": "department_name",
            "yKey": "total_anomalies",
            "label": "Số cảnh báo R1-R8 theo phòng ban",
            "data": rows,
        }
        _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], len(rows), "success", query_type=q_type)
        return _format_response("success", ans, res, chart, user.role)

    # Strategic Route S3: Notable attendance issues ("Những vấn đề attendance nổi bật hiện tại là gì?")
    if any(k in q_lower for k in ["vấn đề", "nổi bật", "tổng quan rủi ro"]) and any(
        k in q_lower for k in ["attendance", "chấm công", "hiện tại", "nổi bật"]
    ):
        res = list_anomalies_tool(conn, user, period=period, severity=severity, rule_code=rule_code)
        rows = res["rows"]
        if not rows:
            ans = "Hiện tại chưa ghi nhận cảnh báo hay vấn đề chấm công nổi bật nào trong phạm vi của bạn."
            _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "insufficient_data", query_type=q_type)
            return _format_response("insufficient_data", ans, res, None, user.role)
        top_lines = [
            f"- [{r['rule_code']} · Mức {r['severity']}] {r['target_code']} ({r['department_name']}, kỳ {r['period']}): {r['explanation']}"
            for r in rows[:5]
        ]
        ans = (
            f"Các vấn đề chấm công nổi bật hiện tại ({len(rows)} cảnh báo R1-R8 trong phạm vi):\n"
            + "\n".join(top_lines)
        )
        _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], len(rows), "success", query_type=q_type)
        return _format_response("success", ans, res, None, user.role)

    # Route A: Anomalies / Cảnh báo bất thường / R1-R8 / Missing punch / Identical / Weekend / Cluster
    if any(
        k in q_lower
        for k in [
            "cảnh báo", "bất thường", "thiếu chấm", "quên chấm", "thiếu giờ",
            "trùng giây", "giống hệt", "cuối tuần", "trùng phòng", "gần lễ", "sát lễ",
        ]
    ) or rule_code is not None:
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

        res = list_anomalies_tool(conn, user, period=period, severity=severity, rule_code=inferred_rule)
        rows = res["rows"]
        if not rows:
            ans = f"Không đủ dữ liệu hoặc không ghi nhận cảnh báo bất thường nào phù hợp trong phạm vi của bạn"
            if period:
                ans += f" cho kỳ {period}."
            else:
                ans += "."
            _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "insufficient_data")
            return _format_response("insufficient_data", ans, res, None, user.role)

        top_lines = [
            f"- [{r['rule_code']} · Mức {r['severity']}] {r['target_code']} ({r['target_name']} – {r['department_name']}, kỳ {r['period']}): {r['explanation']}"
            for r in rows[:5]
        ]
        ans = (
            f"Tìm thấy {len(rows)} cảnh báo bất thường trong phạm vi quyền của bạn"
            f"{f' cho kỳ {period}' if period else ''}:\n" + "\n".join(top_lines)
        )
        _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], len(rows), "success")
        return _format_response("success", ans, res, None, user.role)

    # Route B: Leave balance / Quỹ phép còn lại / Vượt quỹ phép
    if any(k in q_lower for k in ["còn bao nhiêu ngày phép", "quỹ phép", "phép còn lại", "ngày phép năm", "vượt quỹ phép", "dưới "]) and "phép" in q_lower:
        threshold = _extract_threshold(q_lower)
        if "vượt quỹ" in q_lower:
            threshold = -0.1
        res = get_leave_balance(conn, user, threshold=threshold, target_employee_id=target_emp)
        rows = res["rows"]
        if not rows:
            ans = "Không đủ dữ liệu hoặc không có nhân viên nào thỏa mãn điều kiện quỹ phép trong phạm vi của bạn."
            _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "insufficient_data")
            return _format_response("insufficient_data", ans, res, None, user.role)

        if len(rows) == 1:
            r = rows[0]
            ans = (
                f"Nhân viên {r['employee_id']} ({r['full_name']} – Phòng {r['department_name']}) có quỹ phép năm "
                f"{r['annual_leave_balance']} ngày, đã duyệt {r['used_annual_days']} ngày (tính theo ngày lịch), "
                f"còn lại {r['remaining_annual_days']} ngày."
            )
        else:
            lines = [
                f"- {r['employee_id']} ({r['full_name']} – {r['department_name']}): đã dùng {r['used_annual_days']}/{r['annual_leave_balance']} ngày (còn {r['remaining_annual_days']} ngày)"
                for r in rows[:8]
            ]
            ans = f"Danh sách quỹ phép năm ({len(rows)} nhân viên trong phạm vi):\n" + "\n".join(lines)

        _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], len(rows), "success")
        return _format_response("success", ans, res, None, user.role)

    # Route C: Compare department metrics / Phòng ban nào đi muộn cao nhất
    if any(k in q_lower for k in ["phòng nào", "phòng ban nào", "so sánh", "theo phòng ban", "các phòng"]) and "nghỉ phép" not in q_lower:
        res = compare_department_metrics(conn, user, period=effective_period)
        rows = res["rows"]
        if not rows:
            ans = f"Không đủ dữ liệu chấm công cho kỳ {effective_period}."
            _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "insufficient_data")
            return _format_response("insufficient_data", ans, res, None, user.role)

        top = rows[0]
        ans = (
            f"Theo dữ liệu chấm công kỳ {effective_period}, phòng {top['department_name']} có tỷ lệ đi muộn cao nhất "
            f"với {top['late_rate_pct']}% ({top['late_days']} lượt đi muộn / {top['present_days']} ngày đi làm, "
            f"tổng {top['total_work_hours']} giờ công)."
        )
        chart = {
            "type": "bar",
            "xKey": "department_name",
            "yKey": "late_rate_pct",
            "label": "Tỷ lệ đi muộn (%)",
            "data": rows,
        }
        _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], len(rows), "success")
        return _format_response("success", ans, res, chart, user.role)

    # Route D: Leave statistics by department
    if "nghỉ phép" in q_lower or "đơn nghỉ" in q_lower or "đơn phép" in q_lower:
        res = get_leave_by_department(conn, user, period=period)
        rows = res["rows"]
        if not rows:
            ans = f"Không đủ dữ liệu đơn nghỉ phép trong phạm vi của bạn{f' cho kỳ {period}' if period else ''}."
            _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "insufficient_data")
            return _format_response("insufficient_data", ans, res, None, user.role)

        lines = [
            f"- Phòng {r['department_name']}: {r['total_requests']} đơn ({r['approved_requests']} đã duyệt, "
            f"{r['pending_requests']} chờ duyệt, {r['rejected_requests']} từ chối; tổng {r['approved_leave_days']} ngày phép đã duyệt)"
            for r in rows
        ]
        ans = f"Thống kê nghỉ phép{f' kỳ {period}' if period else ''} trong phạm vi của bạn:\n" + "\n".join(lines)
        chart = {
            "type": "bar",
            "xKey": "department_name",
            "yKey": "approved_leave_days",
            "label": "Số ngày nghỉ phép đã duyệt",
            "data": rows,
        }
        _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], len(rows), "success")
        return _format_response("success", ans, res, chart, user.role)

    # Route E: Top late employees / Đi muộn
    if any(k in q_lower for k in ["đi muộn", "trễ", "muộn nhiều nhất"]):
        limit = _extract_limit(q_lower, default=5)
        query_period = None if "quý" in q_lower else effective_period
        res = get_top_late_employees(
            conn,
            user,
            period=query_period,
            limit=limit,
            department_name=mentioned_dept,
        )
        rows = res["rows"]
        if not rows:
            ans = f"Không đủ dữ liệu hoặc không ghi nhận lượt đi muộn nào{f' trong kỳ {query_period}' if query_period else ''}."
            _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "insufficient_data")
            return _format_response("insufficient_data", ans, res, None, user.role)

        if user.role == RoleEnum.employee or len(rows) == 1:
            r = rows[0]
            ans = (
                f"Nhân viên {r['employee_id']} ({r['full_name']} – Phòng {r['department_name']}) đi muộn "
                f"{r['late_days']} lần{f' trong kỳ {query_period}' if query_period else ' trong toàn giai đoạn dữ liệu'} "
                f"(tổng {r['total_late_minutes']} phút, trung bình {r['avg_late_minutes']} phút/lần)."
            )
        else:
            lines = [
                f"{i}. {r['employee_id']} ({r['full_name']} – {r['department_name']}): {r['late_days']} lần đi muộn (tổng {r['total_late_minutes']} phút)"
                for i, r in enumerate(rows, start=1)
            ]
            ans = (
                f"Danh sách {len(rows)} nhân viên đi muộn nhiều nhất"
                f"{f' kỳ {query_period}' if query_period else ''}:\n" + "\n".join(lines)
            )
        _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], len(rows), "success")
        return _format_response("success", ans, res, None, user.role)

    # Route F: Default Attendance Summary
    res = get_attendance_summary(conn, user, period=effective_period, department_name=mentioned_dept)
    rows = res["rows"]
    if not rows:
        ans = f"Không đủ dữ liệu chấm công cho kỳ {effective_period} trong phạm vi của bạn."
        _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], 0, "insufficient_data")
        return _format_response("insufficient_data", ans, res, None, user.role)

    r = rows[0]
    ans = (
        f"Tổng hợp chấm công kỳ {r['period']} ({r['employee_count']} nhân sự trong phạm vi): "
        f"tổng {r['total_work_hours']} giờ công, {r['present_days']} ngày đi làm, "
        f"{r['late_days']} lượt đi muộn (tỷ lệ {r['late_rate_pct']}%), "
        f"{r['missing_punch_days']} lượt thiếu chấm công, {r['leave_days']} ngày nghỉ phép và {r['absent_days']} ngày vắng."
    )
    _log_audit(conn, user, q_clean, res["tool_name"], res["sql_text"], len(rows), "success")
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
