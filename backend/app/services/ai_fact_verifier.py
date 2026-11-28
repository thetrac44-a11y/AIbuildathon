from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Set

# Patterns that must never appear in a grounded AI synthesis (prompt leakage or accusatory verdicts on R1-R8)
UNSAFE_SYNTHESIS_PATTERNS: List[str] = [
    r"password_hash",
    r"jwt_secret",
    r"BEGIN\s+UNTRUSTED\s+REFERENCE",
    r"system_instruction",
]


def _add_numeric_variants(allowed: Set[str], val: Any) -> None:
    """Register exact canonical numeric representations for a verified source number."""
    if isinstance(val, bool) or val is None:
        return
    if isinstance(val, (int, float)):
        fval = abs(float(val))
        allowed.add(f"{fval:g}")
        if fval.is_integer():
            iv = str(int(fval))
            allowed.add(iv)
            allowed.add(f"{int(fval):02d}")
            allowed.add(f"{fval:.1f}")
        else:
            s1 = f"{fval:.1f}".rstrip("0").rstrip(".")
            s2 = f"{fval:.2f}".rstrip("0").rstrip(".")
            allowed.update({s1, s2, f"{fval:.1f}", f"{fval:.2f}", str(fval)})


def _extract_numbers_from_text(text: str) -> List[str]:
    """Extract normalized standalone numbers (supporting both 37.5 and Vietnamese 37,5 decimals & 350.000 thousands)."""
    if not text:
        return []
    # Strip safe identifier/label codes that contain digits but are NOT quantitative facts:
    # - Employee codes: NV007, NV052
    # - Rule codes: R1..R8
    # - Citation tags: DOC-1..DOC-99
    # - Request/Anomaly IDs prefixed with #: #12
    # - Version labels: v1.0, v1.4, v2.0
    # - Markdown bullet numbering at line starts: "1. ", "2. ", "3. "
    cleaned = re.sub(r"\b(?:NV\d+|USR\d+|R[1-8]|DOC-\d+|v\d+(?:\.\d+)*)\b", " ", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"#\d+\b", " ", cleaned)
    cleaned = re.sub(r"(?m)^\s*\d{1,2}\.\s+", " ", cleaned)
    # Strip ISO/VN timestamps HH:MM(:SS) by splitting into component numbers only if needed -> actually extract all numbers from dates/times too
    # First handle Vietnamese thousands-formatted integers like 350.000 or 1.200.000
    found: List[str] = []
    consumed: List[tuple[int, int]] = []

    for m in re.finditer(r"\b\d{1,3}(?:\.\d{3})+\b", cleaned):
        found.append(m.group(0).replace(".", ""))
        consumed.append((m.start(), m.end()))

    def _overlaps(s: int, e: int) -> bool:
        return any(not (e <= cs or s >= ce) for cs, ce in consumed)

    # Decimal or integer tokens (handles both 37.5 and 37,5)
    for m in re.finditer(r"\b\d+(?:[.,]\d+)?\b", cleaned):
        if _overlaps(m.start(), m.end()):
            continue
        raw = m.group(0).replace(",", ".")
        found.append(raw)

    return found


def _normalize_num_token(tok: str) -> str:
    try:
        fval = abs(float(tok))
        if fval.is_integer():
            return str(int(fval))
        return f"{fval:.4f}".rstrip("0").rstrip(".")
    except ValueError:
        return tok


def collect_allowed_numbers(
    sql_evidences: Iterable[Dict[str, Any]],
    rag_chunks: Iterable[Dict[str, Any]],
    extra_text_sources: Iterable[str] = (),
) -> Dict[str, Any]:
    """Collect the complete authoritative set of numbers backed by SQL results and verified RAG chunks."""
    allowed: Set[str] = set()
    sql_fact_count = 0
    rag_fact_count = 0

    for ev in sql_evidences:
        rows = ev.get("rows") or []
        _add_numeric_variants(allowed, len(rows))
        _add_numeric_variants(allowed, ev.get("row_count"))
        sql_fact_count += len(rows)

        # Numbers inside derived deterministic facts (e.g., total_late_minutes, delta_rate, present_days_in_scope)
        for dv in (ev.get("derived_facts") or {}).values():
            if isinstance(dv, (int, float)) and not isinstance(dv, bool):
                _add_numeric_variants(allowed, dv)
                sql_fact_count += 1
            elif isinstance(dv, str):
                for tok in _extract_numbers_from_text(dv):
                    allowed.add(_normalize_num_token(tok))
                    allowed.add(tok)

        # Numbers inside every SQL result row (values + dates/periods/explanations stored in DB)
        for row in rows:
            if not isinstance(row, dict):
                continue
            for val in row.values():
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    _add_numeric_variants(allowed, val)
                    sql_fact_count += 1
                elif isinstance(val, str) and val:
                    for tok in _extract_numbers_from_text(val):
                        allowed.add(_normalize_num_token(tok))
                        allowed.add(tok)

    # Numbers present inside verified, sanitized RAG document chunks & metadata
    for ch in rag_chunks:
        text_body = str(ch.get("sanitized_content") or ch.get("content") or "")
        for tok in _extract_numbers_from_text(text_body):
            allowed.add(_normalize_num_token(tok))
            allowed.add(tok)
            rag_fact_count += 1
        for meta_key in ("page_number", "chunk_index", "version_label", "effective_from", "effective_to"):
            mv = ch.get(meta_key)
            if isinstance(mv, (int, float)):
                _add_numeric_variants(allowed, mv)
            elif isinstance(mv, str):
                for tok in _extract_numbers_from_text(mv):
                    allowed.add(_normalize_num_token(tok))
                    allowed.add(tok)

    # Extra verified structural strings (e.g., target period '2026-10', available periods list, deterministic draft header)
    for txt in extra_text_sources:
        for tok in _extract_numbers_from_text(str(txt or "")):
            allowed.add(_normalize_num_token(tok))
            allowed.add(tok)

    return {
        "allowed": allowed,
        "sql_fact_count": sql_fact_count,
        "rag_fact_count": rag_fact_count,
    }


def verify_response_facts(
    candidate_text: str,
    sql_evidences: List[Dict[str, Any]],
    rag_chunks: List[Dict[str, Any]],
    extra_verified_texts: Optional[List[str]] = None,
    has_insufficient_sql_only: bool = False,
) -> Dict[str, Any]:
    """Verify every standalone number in candidate_text against authoritative SQL & RAG evidence.

    Also verifies:
    - No unsafe prompt/system leakage strings.
    - When SQL returned insufficient_data (no records in DB), candidate_text must NOT fabricate numeric counts or pretend it's 0.
    """
    text = (candidate_text or "").strip()
    if not text:
        return {
            "verified": False,
            "checked_numbers": 0,
            "unverified_numbers": ["<empty_response>"],
            "unsafe_leak": False,
            "sql_fact_count": 0,
            "rag_fact_count": 0,
        }

    # Check for system/prompt leakage
    for pat in UNSAFE_SYNTHESIS_PATTERNS:
        if re.search(pat, text, flags=re.IGNORECASE):
            return {
                "verified": False,
                "checked_numbers": 0,
                "unverified_numbers": ["<unsafe_prompt_leak>"],
                "unsafe_leak": True,
                "sql_fact_count": 0,
                "rag_fact_count": 0,
            }

    # Distinguish insufficient_data vs 0: if SQL had NO attendance/record data at all, forbid claiming "0 lần"
    if has_insufficient_sql_only and re.search(r"\b0\s+(?:lần|ngày|đơn|nhân\s+viên|cảnh\s+báo)\b", text.lower()):
        return {
            "verified": False,
            "checked_numbers": 1,
            "unverified_numbers": ["0 (fabricated_on_insufficient_data)"],
            "unsafe_leak": False,
            "sql_fact_count": 0,
            "rag_fact_count": 0,
        }

    bundle = collect_allowed_numbers(
        sql_evidences=sql_evidences,
        rag_chunks=rag_chunks,
        extra_text_sources=extra_verified_texts or [],
    )
    allowed: Set[str] = bundle["allowed"]

    found = _extract_numbers_from_text(text)
    unverified: List[str] = []
    for raw_tok in found:
        norm = _normalize_num_token(raw_tok)
        if raw_tok not in allowed and norm not in allowed:
            # Also check 1-decimal rounded match ONLY if exact float within 0.001 (prevents 37.5 vs 37.50 mismatch)
            matched_close = False
            try:
                f_tok = float(norm)
                for a in allowed:
                    try:
                        if abs(float(a) - f_tok) < 1e-4:
                            matched_close = True
                            break
                    except ValueError:
                        continue
            except ValueError:
                pass
            if not matched_close and raw_tok not in unverified:
                unverified.append(raw_tok)

    return {
        "verified": len(unverified) == 0,
        "checked_numbers": len(found),
        "unverified_numbers": unverified,
        "unsafe_leak": False,
        "sql_fact_count": bundle["sql_fact_count"],
        "rag_fact_count": bundle["rag_fact_count"],
    }
