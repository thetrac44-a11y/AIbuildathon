from __future__ import annotations

import datetime
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from app.core.security import AuthenticatedUser, build_ai_scope_filter, resolve_ai_effective_scope

# Aliases that require a department prefix ("phòng", "bộ phận", "khối", "team") so phrases like
# "nhân sự toàn công ty" or "quy trình HR" do NOT falsely filter to DEPT_HR.
PREFIX_ONLY_DEPT_ALIASES: Dict[str, str] = {
    "nhân sự": "Nhân sự",
    "nhan su": "Nhân sự",
    "hr": "Nhân sự",
    "tech": "Kỹ thuật",
    "ops": "Vận hành",
    "mkt": "Marketing",
}

# Unambiguous department names/aliases safe to match both with and without prefix.
FREE_DEPT_ALIASES: Dict[str, str] = {
    "kinh doanh": "Kinh doanh",
    "sales": "Kinh doanh",
    "kỹ thuật": "Kỹ thuật",
    "ky thuat": "Kỹ thuật",
    "marketing": "Marketing",
    "vận hành": "Vận hành",
    "van hanh": "Vận hành",
}


def strip_vn_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(ch for ch in nfkd if unicodedata.category(ch) != "Mn")


def get_available_periods(conn: Any) -> List[str]:
    try:
        rows = conn.execute("SELECT DISTINCT period FROM v_attendance_daily ORDER BY period ASC").fetchall()
        return [str(r["period"]) for r in rows if r["period"]]
    except Exception:
        return []


def get_latest_attendance_period(conn: Any, fallback: str = "2026-10") -> str:
    periods = get_available_periods(conn)
    return periods[-1] if periods else fallback


def _shift_month(period: str, delta_months: int) -> str:
    y, m = int(period[:4]), int(period[5:7])
    total = y * 12 + (m - 1) + delta_months
    ny, nm = divmod(total, 12)
    return f"{ny:04d}-{nm + 1:02d}"


def resolve_relative_period(conn: Any, kind: str) -> str:
    """Resolve 'latest', 'current', or 'previous' dynamically from DB attendance periods."""
    periods = get_available_periods(conn)
    latest = periods[-1] if periods else datetime.date.today().strftime("%Y-%m")
    if kind == "latest":
        return latest

    today_ym = datetime.date.today().strftime("%Y-%m")
    current = today_ym if today_ym in periods else latest
    if kind == "current":
        return current
    if kind == "previous":
        return _shift_month(current, -1)
    return latest


def extract_periods_info(q_lower: str, conn: Any) -> Dict[str, Any]:
    """Extract all explicit periods, ranges, quarters, or relative periods from a Vietnamese query."""
    found: List[Tuple[int, str]] = []
    is_range = False
    is_quarter = False
    quarter_label: Optional[str] = None
    default_year = int(get_latest_attendance_period(conn)[:4])

    # 1. Range "MM/YYYY - MM/YYYY" or "MM/YYYY đến MM/YYYY" (e.g. "06/2026–11/2026")
    range_match = re.search(
        r"\b(0?[1-9]|1[0-2])/(20\d{2})\s*(?:[-–—~]|đến|tới)\s*(0?[1-9]|1[0-2])/(20\d{2})\b",
        q_lower,
    )
    if range_match:
        m1, y1, m2, y2 = int(range_match.group(1)), int(range_match.group(2)), int(range_match.group(3)), int(range_match.group(4))
        start_p = f"{y1:04d}-{m1:02d}"
        end_p = f"{y2:04d}-{m2:02d}"
        if start_p <= end_p:
            cur = start_p
            span: List[str] = []
            while cur <= end_p and len(span) < 24:
                span.append(cur)
                cur = _shift_month(cur, 1)
            return {
                "periods": span,
                "primary": span[-1],
                "is_range": True,
                "is_quarter": False,
                "quarter_label": None,
                "explicit": True,
            }

    # 2. Quarter "quý 1..4(/2026 | năm 2026)"
    q_match = re.search(r"\bquý\s*([1-4])(?:\s*(?:/|năm\s*)(20\d{2}))?\b", q_lower)
    if q_match:
        q_num = int(q_match.group(1))
        q_year = int(q_match.group(2)) if q_match.group(2) else default_year
        start_m = (q_num - 1) * 3 + 1
        q_periods = [f"{q_year:04d}-{start_m + i:02d}" for i in range(3)]
        return {
            "periods": q_periods,
            "primary": q_periods[-1],
            "is_range": True,
            "is_quarter": True,
            "quarter_label": f"Quý {q_num}/{q_year}",
            "explicit": True,
        }

    # Track matched spans so we don't double-parse "tháng 10/2026" as both vn_full and vn_month
    consumed_spans: List[Tuple[int, int]] = []

    def _overlaps(s: int, e: int) -> bool:
        return any(not (e <= cs or s >= ce) for cs, ce in consumed_spans)

    # 3. ISO YYYY-MM or YYYY/MM
    for m in re.finditer(r"\b(20\d{2})[-/](0?[1-9]|1[0-2])\b", q_lower):
        # Skip full YYYY-MM-DD calendar dates
        after = q_lower[m.end():m.end() + 3]
        if re.match(r"^-\d{2}\b", after):
            continue
        if not _overlaps(m.start(), m.end()):
            found.append((m.start(), f"{m.group(1)}-{int(m.group(2)):02d}"))
            consumed_spans.append((m.start(), m.end()))

    # 4. Vietnamese "tháng MM/YYYY" or "tháng MM năm YYYY"
    for m in re.finditer(r"tháng\s*(0?[1-9]|1[0-2])\s*(?:/|năm\s*)(20\d{2})\b", q_lower):
        if not _overlaps(m.start(), m.end()):
            found.append((m.start(), f"{m.group(2)}-{int(m.group(1)):02d}"))
            consumed_spans.append((m.start(), m.end()))

    # 5. Bare MM/YYYY (e.g. "10/2026" without "tháng")
    for m in re.finditer(r"(?<!\d/)\b(0?[1-9]|1[0-2])/(20\d{2})\b", q_lower):
        if not _overlaps(m.start(), m.end()):
            found.append((m.start(), f"{m.group(2)}-{int(m.group(1)):02d}"))
            consumed_spans.append((m.start(), m.end()))

    # 6. Vietnamese "tháng MM" (defaults to latest DB year, e.g. 2026)
    for m in re.finditer(r"tháng\s*(0?[1-9]|1[0-2])\b", q_lower):
        if not _overlaps(m.start(), m.end()):
            found.append((m.start(), f"{default_year:04d}-{int(m.group(1)):02d}"))
            consumed_spans.append((m.start(), m.end()))

    # 7. Relative phrases ("tháng này", "kỳ này", "tháng trước", "kỳ gần nhất", "tháng mới nhất")
    if "kỳ gần nhất" in q_lower or "tháng gần nhất" in q_lower or "kỳ mới nhất" in q_lower or "tháng mới nhất" in q_lower:
        pos = min(
            p for p in (
                q_lower.find("kỳ gần nhất"),
                q_lower.find("tháng gần nhất"),
                q_lower.find("kỳ mới nhất"),
                q_lower.find("tháng mới nhất"),
            ) if p >= 0
        )
        found.append((pos, resolve_relative_period(conn, "latest")))
    if "tháng này" in q_lower or "kỳ này" in q_lower:
        pos = q_lower.find("tháng này") if "tháng này" in q_lower else q_lower.find("kỳ này")
        found.append((pos, resolve_relative_period(conn, "current")))
    if "tháng trước" in q_lower or "kỳ trước" in q_lower:
        pos = q_lower.find("tháng trước") if "tháng trước" in q_lower else q_lower.find("kỳ trước")
        found.append((pos, resolve_relative_period(conn, "previous")))

    # Deduplicate preserving chronological appearance order in question
    found.sort(key=lambda item: item[0])
    unique_periods: List[str] = []
    for _, p in found:
        if p not in unique_periods:
            unique_periods.append(p)

    if unique_periods:
        return {
            "periods": unique_periods,
            "primary": unique_periods[0],
            "is_range": is_range,
            "is_quarter": is_quarter,
            "quarter_label": quarter_label,
            "explicit": True,
        }

    latest = get_latest_attendance_period(conn)
    return {
        "periods": [],
        "primary": None,
        "resolved_default": latest,
        "is_range": False,
        "is_quarter": False,
        "quarter_label": None,
        "explicit": False,
    }


def load_department_catalog(conn: Any) -> Dict[str, str]:
    """Load canonical department names dynamically from DB (normalized lowercase -> display name)."""
    catalog: Dict[str, str] = {}
    try:
        rows = conn.execute("SELECT name FROM departments ORDER BY name").fetchall()
        for r in rows:
            name = str(r["name"]).strip()
            if name:
                catalog[name.lower()] = name
                catalog[strip_vn_accents(name).lower()] = name
    except Exception:
        pass
    return catalog


def extract_departments(q_lower: str, conn: Any) -> List[str]:
    """Extract one or more canonical department names dynamically using DB departments + safe aliases."""
    db_depts = load_department_catalog(conn)
    matches: List[Tuple[int, str]] = []

    # Dynamic DB departments + unambiguous aliases (safe with or without prefix)
    free_map: Dict[str, str] = dict(FREE_DEPT_ALIASES)
    for key, canonical in db_depts.items():
        if key not in PREFIX_ONLY_DEPT_ALIASES:
            free_map[key] = canonical

    prefix_pattern = r"(?:phòng(?:\s+ban)?|khối|bộ\s+phận|team|đơn\s+vị)\s+"

    # 1. Check prefix-required aliases strictly with prefix
    for alias, canonical in PREFIX_ONLY_DEPT_ALIASES.items():
        m = re.search(rf"{prefix_pattern}{re.escape(alias)}\b", q_lower)
        if m:
            matches.append((m.start(), canonical))

    # 2. Check free aliases / DB department names (with or without prefix)
    for alias, canonical in free_map.items():
        m = re.search(rf"(?:{prefix_pattern})?\b{re.escape(alias)}\b", q_lower)
        if m:
            matches.append((m.start(), canonical))

    matches.sort(key=lambda item: item[0])
    result: List[str] = []
    for _, canonical in matches:
        if canonical not in result:
            result.append(canonical)
    return result


def extract_employee_codes(question: str) -> List[str]:
    codes: List[str] = []
    for m in re.findall(r"\bNV\d{3}\b", question, flags=re.IGNORECASE):
        u = m.upper()
        if u not in codes:
            codes.append(u)
    return codes


def resolve_employee_name_in_scope(
    conn: Any,
    user: AuthenticatedUser,
    question: str,
) -> Optional[Dict[str, Any]]:
    """Resolve an employee's full name ONLY inside the user's authoritative RBAC scope (zero cross-scope leak)."""
    if resolve_ai_effective_scope(user) in ("none", "self"):
        return None
    scope_sql, scope_params = build_ai_scope_filter(user, "employee_id", "department_id")
    rows = conn.execute(
        f"""
        SELECT employee_id, full_name, department_id, department_name, role
        FROM v_employees
        WHERE {scope_sql}
        ORDER BY employee_id ASC
        """,
        scope_params,
    ).fetchall()

    q_lower = question.lower()
    q_ascii = strip_vn_accents(q_lower)

    # Prefer exact accented match first, then accent-insensitive match (only full names >= 2 words)
    for row in rows:
        fname = str(row["full_name"] or "").strip()
        if len(fname.split()) < 2:
            continue
        if re.search(rf"(?<!\w){re.escape(fname.lower())}(?!\w)", q_lower):
            return dict(row)
    for row in rows:
        fname = str(row["full_name"] or "").strip()
        if len(fname.split()) < 2:
            continue
        f_ascii = strip_vn_accents(fname.lower())
        if re.search(rf"(?<!\w){re.escape(f_ascii)}(?!\w)", q_ascii):
            return dict(row)
    return None


def is_explicit_self_query(
    q_lower: str,
    emp_codes: List[str],
    mentioned_depts: List[str],
    resolved_named_emp: Optional[Dict[str, Any]] = None,
) -> bool:
    """Detect whether a Manager/HR/Executive is explicitly asking about their OWN personal record."""
    if emp_codes or mentioned_depts or resolved_named_emp is not None:
        return False

    # Never treat department/company possessive phrasing as self-only
    if any(
        k in q_lower
        for k in [
            "phòng tôi", "phòng của tôi", "phòng mình", "team tôi", "bộ phận tôi",
            "toàn công ty", "công ty", "các phòng", "phòng nào", "phòng ban nào",
            "nhân viên", "ai đang", "ai còn", "ai là", "bao nhiêu người", "mấy người",
        ]
    ):
        return False

    if any(k in q_lower for k in ["bản thân tôi", "cá nhân tôi", "riêng tôi", "của bản thân"]):
        return True

    # Remove polite framing ("cho tôi xem ...", "giúp tôi ...", "hãy cho tôi biết ...")
    stripped = re.sub(
        r"\b(?:hãy\s+)?(?:cho|giúp|gửi|báo\s+cho)\s+tôi(?:\s+(?:xem|biết|hỏi|kiểm\s*tra|tra\s*cứu))?\b",
        " ",
        q_lower,
    )
    stripped = re.sub(r"\b(?:tôi\s+muốn\s+(?:xem|biết|hỏi|kiểm\s*tra))\b", " ", stripped)

    return bool(re.search(r"\b(?:tôi|của\s+tôi|của\s+mình|mình)\b", stripped))
