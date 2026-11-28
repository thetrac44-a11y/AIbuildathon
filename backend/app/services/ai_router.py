from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Policy / RAG cues: questions asking about company rules, thresholds, procedures, definitions, handbooks, or custom policies.
RAG_POLICY_PATTERNS: List[str] = [
    r"theo\s+(?:quy\s*định|quy\s*chế|nội\s*quy|chính\s*sách|cẩm\s*nang)",
    r"\bquy\s*định\b(?:\s+(?:công\s*ty|như\s+thế\s+nào|thế\s+nào|ra\s+sao|gì|về|cách|hiện\s+hành))?",
    r"\bquy\s*chế\b",
    r"\bnội\s*quy\b",
    r"\bcẩm\s*nang\b",
    r"\bchính\s*sách\b",
    r"\bquy\s*trình\b",
    r"\bthủ\s*tục\b",
    r"\bhướng\s*dẫn\s+(?:xử\s*lý|thực\s*hiện|đổi|tạo|hủy|chấm\s*công)",
    r"\bđề\s*xuất\s+(?:hướng\s*)?xử\s*lý\b",
    r"\bcách\s+xử\s*lý\b",
    r"\bxử\s*lý\s+cảnh\s*báo\b",
    r"\bchạm\s+ngưỡng\b",
    r"\bngưỡng\s+(?:cảnh\s*báo|bao\s+nhiêu|quy\s*định|kích\s*hoạt)\b",
    r"\bđịnh\s*nghĩa\b",
    r"\bcách\s+tính\b",
    r"\bđược\s+tính\s+(?:như\s+thế\s+nào|thế\s+nào|ra\s+sao)\b",
    r"\bquá\s+bao\s+nhiêu\s+phút\s+thì\s+bị\s+tính\b",
    r"\bân\s*hạn\b",
    r"\bgiờ\s+làm\s+việc\s+(?:tiêu\s+chuẩn|hành\s+chính|chuẩn)\b",
    r"\bthời\s+gian\s+nghỉ\s+trưa\b",
    r"\bđiều\s+kiện\s+(?:hủy|duyệt|xin)\b",
    r"\blàm\s+sao\s+(?:để\s+)?(?:tôi\s+)?(?:đổi\s+mật\s+khẩu|hủy\s+đơn|tạo\s+đơn|xin\s+nghỉ)",
    r"\b(?:đổi|thay\s+đổi|cập\s+nhật)\s+mật\s+khẩu\b",
    r"\b(?:phụ\s*cấp|định\s*mức|công\s*tác\s*phí|onboarding|tài\s*liệu\s*nội\s*bộ)\b",
    r"\b(?:mức|tiêu\s*chuẩn)\s+(?:phụ\s*cấp|thưởng|hỗ\s*trợ)\b",
]

# General conversational / capability help patterns (handled without SQL/RAG hallucination)
GENERAL_GREETING_PATTERNS: List[str] = [
    r"^(?:xin\s+)?chào(?:\s+(?:bạn|trợ\s*lý|ai|copilot|em|anh|chị))?[!.?,\s]*$",
    r"^(?:hello|hi|hey)(?:\s+(?:ai|assistant|copilot))?[!.?,\s]*$",
    r"^(?:xin\s+chào[,.!\s]+)?bạn\s+(?:là\s+ai|làm\s+được\s+gì|có\s+thể\s+(?:giúp|hỗ\s+trợ)\s+(?:tôi\s+)?(?:những\s+)?gì|hỗ\s+trợ\s+(?:được\s+)?(?:những\s+)?gì)",
    r"^trợ\s*lý\s+ai\s+(?:làm\s+được\s+gì|hỗ\s+trợ\s+(?:được\s+)?gì)",
    r"^hướng\s*dẫn\s+sử\s+dụng\s+trợ\s*lý(?:\s+ai)?[?!.\s]*$",
    r"^giới\s+thiệu\s+(?:về\s+)?(?:chức\s+năng|trợ\s*lý|hệ\s+thống)[?!.\s]*$",
    r"^cảm\s+ơn(?:\s+(?:bạn|nhiều|trợ\s*lý))?[!.?,\s]*$",
]

# Generic ultra-vague domain-only words that require clarification
GENERIC_AMBIGUOUS_QUERIES = {
    "chấm công", "nghỉ phép", "cảnh báo", "báo cáo", "bất thường",
    "đi muộn", "phép năm", "nhân sự", "thống kê", "tổng hợp",
    "xem chấm công", "xem nghỉ phép", "xem cảnh báo", "xem báo cáo",
    "xem giúp tôi", "kiểm tra giúp tôi", "tra cứu giúp tôi", "giúp tôi",
}

HR_DOMAIN_KEYWORDS = [
    "đi muộn", "trễ", "chấm công", "attendance", "giờ công", "nghỉ phép", "phép", "quỹ phép",
    "cảnh báo", "bất thường", "thiếu chấm", "quên chấm", "cuối tuần", "trùng",
    "r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "so sánh", "phòng ban", "phòng nào",
    "nv0", "tổng hợp", "chuyên cần", "thống kê tháng", "xu hướng", "nổi bật", "3 tháng", "6 tháng",
    "nhân sự", "trưởng phòng", "danh sách nhân viên", "chờ duyệt", "phê duyệt", "ban điều hành",
    "đơn nghỉ", "đơn phép", "tăng ca", "ngày lễ", "đúng giờ", "hiệu suất", "mật độ rủi ro",
    "quy định", "quy chế", "nội quy", "chính sách", "cẩm nang", "quy trình", "mật khẩu",
    "phụ cấp", "định mức", "ân hạn", "giờ làm việc", "hủy đơn", "onboarding",
]


@dataclass
class SubQuery:
    kind: str  # "sql" | "rag"
    intent: str
    query_text: str
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "intent": self.intent,
            "query_text": self.query_text,
            "params": self.params,
        }


@dataclass
class RoutingPlan:
    route_type: str  # "SQL_ONLY" | "RAG_ONLY" | "HYBRID" | "GENERAL" | "CLARIFICATION"
    sub_queries: List[SubQuery] = field(default_factory=list)
    rationale: str = ""
    used_context: bool = False
    is_multi_intent: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.route_type,
            "sub_queries": [sq.to_dict() for sq in self.sub_queries],
            "rationale": self.rationale,
            "used_context": self.used_context,
            "is_multi_intent": self.is_multi_intent,
        }


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


def _has_rag_policy_signal(q_lower: str) -> bool:
    return any(re.search(pat, q_lower) for pat in RAG_POLICY_PATTERNS)


def _is_general_greeting(q_lower: str) -> bool:
    return any(re.search(pat, q_lower) for pat in GENERAL_GREETING_PATTERNS)


def _build_focused_rag_query(
    question: str,
    rule_codes: List[str],
    q_lower: str,
) -> str:
    """Construct a focused RAG search query from a hybrid or policy question without SQL noise."""
    # Extract the policy clause when joined by 'và' / ',' so BM25 + Vector focus cleanly on policy terms
    parts = re.split(r"(?:\bvà\b|,|;|\?)", question, flags=re.IGNORECASE)
    policy_parts: List[str] = []
    for p in parts:
        p_clean = p.strip()
        if not p_clean:
            continue
        if _has_rag_policy_signal(p_clean.lower()) or any(
            k in p_clean.lower()
            for k in ["r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "tăng ca", "cuối tuần", "phép năm", "hủy đơn", "mật khẩu", "đi muộn", "ân hạn"]
        ):
            # Exclude pure data clauses like "Tháng 10/2026 tôi đi muộn mấy lần" when another explicit policy clause exists
            policy_parts.append(p_clean)

    explicit_policy_only = [p for p in policy_parts if _has_rag_policy_signal(p.lower())]
    if explicit_policy_only:
        focused = " ".join(explicit_policy_only)
    else:
        focused = question.strip()

    # Keep explicit rule codes R1-R8 attached for razor-sharp chunk ranking (e.g., TC-26, TC-27, TC-28, TC-29)
    for rc in rule_codes:
        if rc.lower() not in focused.lower():
            focused = f"{focused} quy tắc {rc}"

    # Contextual keyword enrichment for hybrid questions that mention topic in the first clause
    if ("tăng ca" in q_lower or "cuối tuần" in q_lower or "R7" in rule_codes) and "tăng ca" not in focused.lower():
        focused = f"{focused} làm thêm giờ tăng ca cuối tuần R7"
    if ("nghỉ trùng" in q_lower or "R5" in rule_codes) and "r5" not in focused.lower():
        focused = f"{focused} cảnh báo R5 nghỉ trùng phòng ban"
    if ("vượt quỹ phép" in q_lower or "R8" in rule_codes) and "phép năm" not in focused.lower():
        focused = f"{focused} cách tính ngày phép năm vượt quỹ phép R8"
    if ("đi muộn" in q_lower or "R1" in rule_codes) and "đi muộn" not in focused.lower():
        focused = f"{focused} đi muộn ân hạn 5 phút quy tắc R1"

    return focused.strip()


def _detect_sql_sub_queries(
    question: str,
    q_lower: str,
    entities: Dict[str, Any],
    has_rag_signal: bool,
) -> List[SubQuery]:
    """Detect one or more concrete SQL sub-queries, supporting both single-intent and multi-intent questions.

    Carefully avoids firing SQL tools on pure policy/procedure questions (e.g. TC-07, TC-08, TC-09).
    """
    emp_codes: List[str] = entities.get("emp_codes") or []
    mentioned_depts: List[str] = entities.get("mentioned_depts") or []
    mentioned_dept: Optional[str] = mentioned_depts[0] if mentioned_depts else None
    target_emp: Optional[str] = entities.get("target_emp")
    force_self: bool = bool(entities.get("force_self"))
    period_info: Dict[str, Any] = entities.get("period_info") or {}
    explicit_periods: List[str] = period_info.get("periods") or []
    period: Optional[str] = period_info.get("primary")
    query_periods: Optional[List[str]] = (
        explicit_periods if (period_info.get("is_range") or period_info.get("is_quarter")) else None
    )
    rule_codes: List[str] = entities.get("rule_codes") or []
    rule_code: Optional[str] = rule_codes[0] if rule_codes else None
    severity: Optional[str] = entities.get("severity")
    leave_status: Optional[str] = entities.get("leave_status")
    explicit_date: Optional[str] = entities.get("explicit_date")
    inherited_sql_intent: Optional[str] = entities.get("inherited_sql_intent")

    # 0. Follow-up inherited SQL intent (e.g., Turn 2 "Còn tháng 9 thì sao?")
    if inherited_sql_intent:
        return [
            SubQuery(
                kind="sql",
                intent=inherited_sql_intent,
                query_text=question,
                params={
                    "period": period,
                    "periods": query_periods,
                    "department_name": mentioned_dept,
                    "department_names": mentioned_depts,
                    "target_emp": target_emp,
                    "force_self": force_self,
                    "rule_code": rule_code,
                    "severity": severity,
                    "leave_status": leave_status,
                    "limit": _extract_limit(q_lower, default=5),
                    "threshold": _extract_threshold(q_lower),
                },
            )
        ]

    # Guard against hijacking PURE policy/procedure questions (TC-07, TC-08, TC-09, custom RAG docs) into SQL!
    if has_rag_signal:
        has_operational_target = (
            bool(emp_codes)
            or target_emp is not None
            or bool(mentioned_depts)
            or bool(explicit_periods)
            or explicit_date is not None
            or any(
                re.search(pat, q_lower)
                for pat in [
                    r"\b(?:tôi|của\s+tôi|phòng\s+tôi|phòng\s+của\s+tôi|toàn\s+công\s+ty)\b",
                    r"\b(?:ai\s+đang|những\s+ai|gồm\s+những\s+ai|liệt\s+kê|thống\s+kê|tổng\s+hợp|tóm\s+tắt\s+rủi\s+ro|so\s+sánh|xu\s+hướng)\b",
                    r"\b(?:có\s+cảnh\s+báo\s+(?:r[1-8]\s+)?nào|đã\s+có\s+đơn\s+tăng\s+ca|đang\s+vượt\s+quỹ|đi\s+muộn\s+(?:mấy|bao\s+nhiêu)\s+lần|còn\s+bao\s+nhiêu\s+ngày\s+phép)\b",
                    r"\b(?:họ\s+đã\s+có\s+đơn|có\s+đơn\s+nghỉ\s+phép\s+nào\s+đang\s+chờ)\b",
                ]
            )
        )
        # Exclude pure self-service help ("Làm sao để tôi đổi mật khẩu tài khoản của mình?")
        is_pure_account_help = any(k in q_lower for k in ["đổi mật khẩu", "thay đổi mật khẩu", "cập nhật mật khẩu"]) and not any(
            k in q_lower for k in ["chấm công", "đi muộn", "nghỉ phép", "cảnh báo"]
        )
        # Exclude "Theo quy định công ty..." where "công ty" only appears inside "quy định công ty" / "nội quy công ty"
        q_without_policy_company = re.sub(
            r"(?:quy\s*định|quy\s*chế|nội\s*quy|chính\s*sách|cẩm\s*nang)\s+(?:của\s+)?công\s*ty",
            "",
            q_lower,
        )
        if is_pure_account_help:
            return []
        if not has_operational_target:
            return []
        # Double-check: if the ONLY trigger was "tôi" inside "cho tôi hỏi quy định..." or "giúp tôi xem quy định...", it's RAG_ONLY
        stripped_polite = re.sub(
            r"\b(?:hãy\s+)?(?:cho|giúp|gửi|báo\s+cho)\s+tôi(?:\s+(?:xem|biết|hỏi|kiểm\s*tra|tra\s*cứu))?\b",
            " ",
            q_without_policy_company,
        )
        stripped_polite = re.sub(r"\btôi\s+muốn\s+(?:hỏi|biết|xem)\b", " ", stripped_polite)
        has_real_op_after_strip = (
            bool(emp_codes)
            or target_emp is not None
            or bool(mentioned_depts)
            or bool(explicit_periods)
            or explicit_date is not None
            or any(
                re.search(pat, stripped_polite)
                for pat in [
                    r"\b(?:tôi\s+(?:đi\s+muộn|còn|có|đã\s+chấm|chấm\s+công)|của\s+tôi|phòng\s+tôi|toàn\s+công\s+ty)\b",
                    r"\b(?:ai\s+đang|những\s+ai|gồm\s+những\s+ai|liệt\s+kê|thống\s+kê|tổng\s+hợp|tóm\s+tắt\s+rủi\s+ro|so\s+sánh|xu\s+hướng)\b",
                    r"\b(?:có\s+cảnh\s+báo\s+(?:r[1-8]\s+)?nào|đã\s+có\s+đơn\s+tăng\s+ca|đang\s+vượt\s+quỹ|đi\s+muộn\s+(?:mấy|bao\s+nhiêu)\s+lần|còn\s+bao\s+nhiêu\s+ngày\s+phép)\b",
                    r"\b(?:họ\s+đã\s+có\s+đơn|có\s+đơn\s+nghỉ\s+phép\s+nào\s+đang\s+chờ)\b",
                ]
            )
        )
        if not has_real_op_after_strip:
            return []

    sub_queries: List[SubQuery] = []

    def _add_sq(intent: str, params: Optional[Dict[str, Any]] = None) -> None:
        if any(sq.intent == intent and sq.params == (params or {}) for sq in sub_queries):
            return
        sub_queries.append(SubQuery(kind="sql", intent=intent, query_text=question, params=params or {}))

    # --- 1. Daily attendance ("Hôm nay tôi đã chấm công chưa?" / YYYY-MM-DD) ---
    if (
        ("hôm nay" in q_lower or explicit_date is not None)
        and any(k in q_lower for k in ["chấm công", "check-in", "check in", "đi làm", "vào ca", "ra ca"])
        and not any(k in q_lower for k in ["cảnh báo", "bất thường", "quỹ phép"])
    ):
        _add_sq("daily_attendance", {"work_date": explicit_date})
        return sub_queries

    # --- 2. Two-period comparison (TC-13) ---
    if (
        len(explicit_periods) == 2
        and not period_info.get("is_range")
        and any(k in q_lower for k in ["so sánh", "giữa", "so với", "chênh lệch", "thay đổi"])
    ):
        _add_sq("compare_periods", {"period_a": explicit_periods[0], "period_b": explicit_periods[1]})
        return sub_queries

    # --- 3. Multi-month trend (TC-22) ---
    if (
        any(k in q_lower for k in ["xu hướng", "nhiều tháng", "theo tháng", "gần đây", "biến động"])
        or bool(re.search(r"\b[2-9]\s*tháng\b|\b1[0-2]\s*tháng\b", q_lower))
        or (period_info.get("is_range") and not period_info.get("is_quarter") and len(explicit_periods) >= 3)
    ) and any(k in q_lower for k in ["chấm công", "attendance", "đi muộn", "đi làm", "tháng", "tỷ lệ"]):
        m_cnt = re.search(r"(\d+)\s*tháng", q_lower)
        months = int(m_cnt.group(1)) if m_cnt else (len(explicit_periods) if period_info.get("is_range") else 3)
        _add_sq("attendance_trend", {"months": months})
        return sub_queries

    # --- 4. Department risk ranking by R1-R8 (TC-24) ---
    if (
        any(k in q_lower for k in ["phòng nào", "phòng ban nào", "theo phòng", "nhiều cảnh báo", "mật độ rủi ro"])
        and any(k in q_lower for k in ["cảnh báo", "bất thường", "r1", "r8", "rủi ro"])
    ):
        _add_sq("anomalies_by_department", {"open_only": "đang mở" in q_lower})
        return sub_queries

    # --- 5. Full Multi-KPI / 2-Department Comparison (TC-21, TC-25) ---
    is_two_dept_compare = len(mentioned_depts) >= 2 and any(
        k in q_lower for k in ["so sánh", "giữa", "với", "hiệu suất", "chuyên cần"]
    )
    is_full_exec_compare = any(k in q_lower for k in ["so sánh", "phòng nào", "phòng ban nào", "5 phòng", "các phòng"]) and (
        any(k in q_lower for k in ["toàn diện", "đúng giờ", "hiệu suất", "chuyên cần"])
        or ("đi muộn" in q_lower and "nghỉ phép" in q_lower)
        or ("cảnh báo" in q_lower and ("đi muộn" in q_lower or "đúng giờ" in q_lower))
    )
    if is_two_dept_compare or is_full_exec_compare:
        _add_sq("compare_departments_full", {"department_names": mentioned_depts if len(mentioned_depts) >= 2 else None})
        return sub_queries

    # --- 6. Standard single-metric department late ranking ("Phòng nào đi muộn cao nhất?") ---
    if (
        any(k in q_lower for k in ["phòng nào", "phòng ban nào", "so sánh", "theo phòng ban", "các phòng"])
        and "nghỉ phép" not in q_lower
        and not any(k in q_lower for k in ["cảnh báo", "bất thường"])
    ):
        _add_sq("compare_department_metrics", {})
        return sub_queries

    # --- 7. Executive/Overview Notable Risk Summary (TC-30 & S3) ---
    if any(k in q_lower for k in ["tóm tắt rủi ro", "vấn đề", "nổi bật", "tổng quan rủi ro"]) and any(
        k in q_lower for k in ["attendance", "chấm công", "hiện tại", "nổi bật", "rủi ro", "kỳ gần nhất"]
    ):
        _add_sq("notable_anomalies", {"severity": severity, "rule_code": rule_code})
        if "rủi ro" in q_lower or "kỳ gần nhất" in q_lower:
            _add_sq("attendance_summary", {})
        return sub_queries

    # =========================================================================
    # 8. COMPOSABLE MULTI-INTENT SQL DETECTION (SUPPORTS 1 TO 4 ORTHOGONAL INTENTS!)
    # =========================================================================

    # 8A. Employee directory & department manager (TC-18, or combined with anomalies/late)
    wants_directory = any(
        k in q_lower
        for k in [
            "bao nhiêu nhân sự", "bao nhiêu nhân viên", "ai là trưởng phòng",
            "trưởng phòng là ai", "danh sách nhân viên", "cơ cấu nhân sự", "chức danh",
        ]
    ) and not any(k in q_lower for k in ["bao nhiêu nhân viên đi muộn", "bao nhiêu nhân viên nghỉ"])
    if wants_directory:
        _add_sq("employee_directory", {})

    # 8B. Anomalies R1-R8 (including TC-17 dual high + R8, TC-27 R5, TC-28 R8, TC-29 R7!)
    # Note: In TC-26 ("Tháng 10/2026 tôi đi muộn mấy lần và theo quy chế công ty, mức này có chạm ngưỡng cảnh báo R1 không?"),
    # the user asks their late count + policy threshold R1 (not listing anomalies), so distinguish "chạm ngưỡng cảnh báo R1"
    is_only_threshold_question = (
        "chạm ngưỡng" in q_lower
        and "đi muộn" in q_lower
        and not any(k in q_lower for k in ["có cảnh báo", "cảnh báo nào", "liệt kê", "gồm những ai", "ai đang"])
    )
    wants_anomalies = (
        not is_only_threshold_question
        and (
            any(
                k in q_lower
                for k in [
                    "cảnh báo", "bất thường", "thiếu chấm", "quên chấm", "thiếu giờ",
                    "trùng giây", "giống hệt", "trùng phòng", "gần lễ", "sát lễ",
                ]
            )
            or (rule_code is not None and not is_only_threshold_question)
            or ("vượt quỹ phép" in q_lower and ("ai đang" in q_lower or "nhân viên đang" in q_lower or "r8" in q_lower))
        )
    )
    if wants_anomalies:
        is_dual_high_and_r8 = (
            severity == "high"
            and (rule_code == "R8" or "vượt quỹ phép" in q_lower)
            and any(k in q_lower for k in [" và ", " cùng ", " đồng thời "])
        )
        if is_dual_high_and_r8:
            _add_sq("anomalies_list", {"severity": "high", "rule_code": None, "label": "high_anomalies"})
            _add_sq("anomalies_list", {"severity": None, "rule_code": "R8", "label": "r8_anomalies"})
        else:
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
            _add_sq("anomalies_list", {"severity": severity, "rule_code": inferred_rule})

    # 8C. Leave balance (TC-03, TC-15, TC-28 over-balance detail)
    threshold = _extract_threshold(q_lower)
    is_leave_balance_q = (
        "phép" in q_lower
        and any(k in q_lower for k in ["còn bao nhiêu ngày phép", "quỹ phép", "phép còn lại", "ngày phép năm", "vượt quỹ phép"])
        and not ("cách tính số ngày phép năm" in q_lower and "còn bao nhiêu" not in q_lower and "vượt quỹ" not in q_lower)
    ) or (
        "phép" in q_lower
        and threshold is not None
        and not any(k in q_lower for k in ["phòng nào", "phòng ban nào"])
    )
    if is_leave_balance_q and not (severity == "high" and rule_code == "R8"):
        eff_thresh = -0.1 if "vượt quỹ" in q_lower else threshold
        _add_sq("leave_balance", {"threshold": eff_thresh})

    # 8D. Leave requests detail or department leave stats (TC-03 part 2, TC-12, TC-19, TC-23, multi-intent!)
    exec_approval_only = any(
        k in q_lower for k in ["ban điều hành", "cấp cao", "đặc biệt", "lãnh đạo phê duyệt", "requires_executive_approval"]
    )
    wants_leave_detail = (
        exec_approval_only
        or (
            any(k in q_lower for k in ["đơn nghỉ", "đơn phép", "đơn nào", "nghỉ phép nào", "đơn nghỉ phép"])
            and (
                leave_status is not None
                or any(k in q_lower for k in ["những đơn nào", "danh sách đơn", "đơn nào đang", "chi tiết đơn", "chờ duyệt", "của tôi"])
                or target_emp is not None
            )
        )
        or (
            "nghỉ phép" in q_lower
            and leave_status is not None
            and not any(k in q_lower for k in ["quy trình", "hủy đơn"])
        )
    )
    wants_leave_stats = (
        not wants_leave_detail
        and not is_leave_balance_q
        and not wants_anomalies
        and any(k in q_lower for k in ["thống kê nghỉ phép", "tình hình nghỉ phép", "nghỉ phép theo phòng", "nghỉ phép của"])
    )
    if wants_leave_detail:
        _add_sq(
            "leave_requests_detail",
            {
                "status_filter": leave_status or ("pending" if exec_approval_only else None),
                "requires_executive_approval": True if exec_approval_only else None,
            },
        )
    elif wants_leave_stats:
        _add_sq("leave_by_department", {})

    # 8E. Overtime / Holidays (TC-29 cross-check + Route H)
    wants_overtime_sql = any(
        k in q_lower for k in ["đơn tăng ca", "có đơn tăng ca", "đơn làm thêm", "ngày lễ công ty", "danh sách ngày lễ"]
    ) or (
        any(k in q_lower for k in ["tăng ca", "overtime", "làm thêm giờ", "ngày lễ"])
        and not wants_anomalies
        and not has_rag_signal
    )
    if wants_overtime_sql:
        _add_sq("holidays_overtime", {"ask_overtime": any(k in q_lower for k in ["tăng ca", "overtime", "làm thêm"])})

    # 8F. Late attendance (TC-01, TC-04, TC-05, TC-11, TC-16, TC-20, TC-26, multi-intent!)
    wants_late_sql = any(k in q_lower for k in ["đi muộn", "trễ", "muộn nhiều nhất"]) and not (
        wants_anomalies and "mấy lần" not in q_lower and "bao nhiêu" not in q_lower and "top " not in q_lower
    )
    if wants_late_sql:
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
            _add_sq(
                "employee_attendance_detail",
                {
                    "filter_type": "late",
                    "order_by": order_by,
                    "limit": detail_limit,
                    "wants_top_personal_days": wants_top_personal_days,
                },
            )
        elif (target_emp is not None or force_self) and any(k in q_lower for k in ["giờ công", "tổng giờ", "tổng hợp"]):
            # TC-16: Specific employee late count + work hours
            _add_sq("attendance_summary", {})
            _add_sq("top_late_employees", {"limit": 5, "asking_total_count": False})
        else:
            asking_total_count = any(k in q_lower for k in ["bao nhiêu người", "mấy người", "có bao nhiêu nhân viên"])
            limit = _extract_limit(q_lower, default=50 if asking_total_count else 5)
            _add_sq("top_late_employees", {"limit": limit, "asking_total_count": asking_total_count})

    # 8G. Explicit attendance summary (when asked alongside another intent or standalone)
    wants_summary_sql = any(
        k in q_lower for k in ["tổng hợp chấm công", "thống kê chấm công", "tổng giờ công", "tổng số giờ công", "chấm công của"]
    )
    if wants_summary_sql and not any(sq.intent in ("attendance_summary", "employee_attendance_detail") for sq in sub_queries):
        _add_sq("attendance_summary", {})

    # 8H. Fallback default SQL summary ONLY when no sub-queries matched yet AND there is clear operational intent
    if not sub_queries and not has_rag_signal:
        has_any_sql_domain = any(
            k in q_lower
            for k in [
                "chấm công", "attendance", "giờ công", "đi làm", "vắng", "đúng giờ",
                "chuyên cần", "thống kê tháng", "tổng hợp",
            ]
        ) or (bool(explicit_periods) and (target_emp is not None or mentioned_dept is not None or force_self))
        if has_any_sql_domain:
            _add_sq("attendance_summary", {})

    return sub_queries[:4]


def route_query(
    question: str,
    entities: Dict[str, Any],
    used_context: bool = False,
) -> RoutingPlan:
    """Classify a user query into SQL_ONLY / RAG_ONLY / HYBRID / GENERAL / CLARIFICATION with multi-intent sub-queries."""
    q_clean = (question or "").strip()
    q_lower = q_clean.lower()
    q_norm = re.sub(r"[?!.,:;]+$", "", q_lower).strip()
    words = [w for w in q_norm.split() if w]

    # 1. General greeting / capability help (only if no operational or policy content)
    if _is_general_greeting(q_lower) and not entities.get("inherited_sql_intent"):
        return RoutingPlan(
            route_type="GENERAL",
            sub_queries=[],
            rationale="Câu hỏi chào hỏi hoặc hỏi khả năng hỗ trợ chung của Trợ lý AI.",
            used_context=used_context,
            is_multi_intent=False,
        )

    # 2. Ambiguous / too-short / vague requests -> CLARIFICATION (preserves Q22 "Xem giúp tôi")
    emp_codes = entities.get("emp_codes") or []
    target_emp = entities.get("target_emp")
    rule_codes = entities.get("rule_codes") or []
    period = (entities.get("period_info") or {}).get("primary")
    severity = entities.get("severity")
    inherited = entities.get("inherited_sql_intent")

    is_generic_short = (
        q_norm in GENERIC_AMBIGUOUS_QUERIES
        or (
            len(words) <= 2
            and not emp_codes
            and not target_emp
            and not rule_codes
            and not period
            and not severity
            and not inherited
        )
    )
    if (len(q_clean) < 8 or is_generic_short) and not inherited:
        return RoutingPlan(
            route_type="CLARIFICATION",
            sub_queries=[],
            rationale="Câu hỏi quá ngắn hoặc chung chung, cần làm rõ chỉ số và thời gian.",
            used_context=used_context,
            is_multi_intent=False,
        )

    has_rag_signal = _has_rag_policy_signal(q_lower)
    sql_sub_queries = _detect_sql_sub_queries(q_clean, q_lower, entities, has_rag_signal=has_rag_signal)

    # 3. HYBRID: BOTH operational SQL sub-queries AND policy/procedure RAG query
    if sql_sub_queries and has_rag_signal:
        rag_q = _build_focused_rag_query(q_clean, rule_codes, q_lower)
        all_sq = [*sql_sub_queries[:3], SubQuery(kind="rag", intent="policy_retrieval", query_text=rag_q)]
        return RoutingPlan(
            route_type="HYBRID",
            sub_queries=all_sq,
            rationale=(
                f"Câu hỏi kết hợp {len(sql_sub_queries)} truy vấn dữ liệu thực tế (SQL) "
                "và tra cứu quy định/quy trình nội bộ (RAG)."
            ),
            used_context=used_context,
            is_multi_intent=True,
        )

    # 4. SQL_ONLY: One or more operational SQL sub-queries
    if sql_sub_queries:
        return RoutingPlan(
            route_type="SQL_ONLY",
            sub_queries=sql_sub_queries,
            rationale=(
                f"Truy vấn dữ liệu vận hành gồm {len(sql_sub_queries)} ý qua SQL Intelligence có kiểm soát RBAC."
            ),
            used_context=used_context,
            is_multi_intent=len(sql_sub_queries) > 1,
        )

    # 5. RAG_ONLY: Always pass the FULL question so multi-clause policy queries (e.g. "xin nghỉ phép năm và hủy đơn chờ duyệt") keep 100% of their terms!
    if has_rag_signal or len(words) >= 4:
        return RoutingPlan(
            route_type="RAG_ONLY",
            sub_queries=[SubQuery(kind="rag", intent="policy_retrieval", query_text=q_clean)],
            rationale="Truy vấn quy định, chính sách, quy trình hoặc tài liệu nội bộ qua RAG Intelligence.",
            used_context=used_context,
            is_multi_intent=False,
        )

    # 6. Fallback clarification for anything else short/unclear
    return RoutingPlan(
        route_type="CLARIFICATION",
        sub_queries=[],
        rationale="Chưa xác định rõ nhu cầu tra cứu dữ liệu hay quy định.",
        used_context=used_context,
        is_multi_intent=False,
    )
