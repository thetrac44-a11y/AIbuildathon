from __future__ import annotations

import datetime
import json
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, status

from app.db.connection import is_postgres_connection

MAX_CONTEXT_TURNS = 6


def _parse_json_obj(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}


def _now_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_or_create_conversation(
    conn: Any,
    user_id: str,
    conversation_id: Optional[str],
    initial_question: str,
) -> Tuple[str, Dict[str, Any], bool]:
    """Load an existing user-owned conversation or create a new one.

    Strictly isolates by user_id: if a user supplies a conversation_id owned by another user
    (or non-existent), raises HTTP 404 (anti-enumeration & strict isolation).
    """
    if conversation_id and conversation_id.strip():
        cid = conversation_id.strip()
        row = conn.execute(
            """
            SELECT conversation_id, user_id, title, context_json, created_at, updated_at
            FROM ai_conversations
            WHERE conversation_id = ? AND user_id = ?
            LIMIT 1
            """,
            (cid, user_id),
        ).fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy phiên hội thoại hoặc bạn không có quyền truy cập.",
            )
        return cid, _parse_json_obj(row["context_json"]), False

    new_id = f"conv_{uuid.uuid4().hex[:16]}"
    title = (initial_question.strip()[:80] + ("..." if len(initial_question.strip()) > 80 else "")) or "Hội thoại mới"
    now = _now_str()
    pg = is_postgres_connection(conn)
    if pg:
        conn.execute(
            """
            INSERT INTO public.ai_conversations (conversation_id, user_id, title, context_json, created_at, updated_at)
            VALUES (?, ?, ?, ?::jsonb, ?, ?)
            """,
            (new_id, user_id, title, "{}", now, now),
        )
    else:
        conn.execute(
            """
            INSERT INTO ai_conversations (conversation_id, user_id, title, context_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (new_id, user_id, title, "{}", now, now),
        )
    return new_id, {}, True


def save_conversation_turn(
    conn: Any,
    conversation_id: str,
    user_id: str,
    user_question: str,
    assistant_response: Dict[str, Any],
    updated_context: Dict[str, Any],
) -> None:
    """Persist both the user message and structured assistant response, and update conversation context."""
    now = _now_str()
    route_type = (assistant_response.get("route") or {}).get("type")
    resp_json = json.dumps(assistant_response, ensure_ascii=False, default=str)
    ctx_json = json.dumps(updated_context, ensure_ascii=False, default=str)
    pg = is_postgres_connection(conn)

    if pg:
        conn.execute(
            """
            INSERT INTO public.ai_messages (conversation_id, user_id, role, content, route_type, response_json, created_at)
            VALUES (?, ?, 'user', ?, ?, NULL, ?)
            """,
            (conversation_id, user_id, user_question[:1000], route_type, now),
        )
        conn.execute(
            """
            INSERT INTO public.ai_messages (conversation_id, user_id, role, content, route_type, response_json, created_at)
            VALUES (?, ?, 'assistant', ?, ?, ?::jsonb, ?)
            """,
            (conversation_id, user_id, str(assistant_response.get("answer") or ""), route_type, resp_json, now),
        )
        conn.execute(
            """
            UPDATE public.ai_conversations
            SET context_json = ?::jsonb, updated_at = ?
            WHERE conversation_id = ? AND user_id = ?
            """,
            (ctx_json, now, conversation_id, user_id),
        )
    else:
        conn.execute(
            """
            INSERT INTO ai_messages (conversation_id, user_id, role, content, route_type, response_json, created_at)
            VALUES (?, ?, 'user', ?, ?, NULL, ?)
            """,
            (conversation_id, user_id, user_question[:1000], route_type, now),
        )
        conn.execute(
            """
            INSERT INTO ai_messages (conversation_id, user_id, role, content, route_type, response_json, created_at)
            VALUES (?, ?, 'assistant', ?, ?, ?, ?)
            """,
            (conversation_id, user_id, str(assistant_response.get("answer") or ""), route_type, resp_json, now),
        )
        conn.execute(
            """
            UPDATE ai_conversations
            SET context_json = ?, updated_at = ?
            WHERE conversation_id = ? AND user_id = ?
            """,
            (ctx_json, now, conversation_id, user_id),
        )
    conn.commit()


def list_user_conversations(conn: Any, user_id: str, limit: int = 30) -> List[Dict[str, Any]]:
    """Read-only list of conversations strictly for user_id (ZERO re-query, ZERO audit log written)."""
    rows = conn.execute(
        """
        SELECT
            c.conversation_id,
            c.title,
            c.created_at,
            c.updated_at,
            (SELECT COUNT(*) FROM ai_messages m WHERE m.conversation_id = c.conversation_id) AS message_count
        FROM ai_conversations c
        WHERE c.user_id = ?
        ORDER BY c.updated_at DESC, c.created_at DESC
        LIMIT ?
        """,
        (user_id, max(1, min(int(limit), 100))),
    ).fetchall()
    return [
        {
            "conversation_id": r["conversation_id"],
            "title": r["title"],
            "created_at": str(r["created_at"]),
            "updated_at": str(r["updated_at"]),
            "message_count": int(r["message_count"] or 0),
        }
        for r in rows
    ]


def get_user_conversation_detail(conn: Any, user_id: str, conversation_id: str) -> Dict[str, Any]:
    """Read-only load of a full conversation & its stored messages (ZERO SQL/LLM re-execution, ZERO audit log)."""
    conv = conn.execute(
        """
        SELECT conversation_id, user_id, title, context_json, created_at, updated_at
        FROM ai_conversations
        WHERE conversation_id = ? AND user_id = ?
        LIMIT 1
        """,
        (conversation_id, user_id),
    ).fetchone()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy phiên hội thoại hoặc bạn không có quyền truy cập.",
        )

    msg_rows = conn.execute(
        """
        SELECT message_id, role, content, route_type, response_json, created_at
        FROM ai_messages
        WHERE conversation_id = ? AND user_id = ?
        ORDER BY message_id ASC
        """,
        (conversation_id, user_id),
    ).fetchall()

    messages: List[Dict[str, Any]] = []
    for m in msg_rows:
        resp_obj = _parse_json_obj(m["response_json"]) if m["response_json"] else None
        messages.append(
            {
                "message_id": int(m["message_id"]),
                "role": m["role"],
                "content": m["content"],
                "route_type": m["route_type"],
                "response": resp_obj,
                "created_at": str(m["created_at"]),
            }
        )

    return {
        "conversation_id": conv["conversation_id"],
        "title": conv["title"],
        "created_at": str(conv["created_at"]),
        "updated_at": str(conv["updated_at"]),
        "context": _parse_json_obj(conv["context_json"]),
        "messages": messages,
    }


def delete_user_conversation(conn: Any, user_id: str, conversation_id: str) -> Dict[str, Any]:
    """Delete a conversation strictly owned by user_id."""
    conv = conn.execute(
        "SELECT conversation_id FROM ai_conversations WHERE conversation_id = ? AND user_id = ? LIMIT 1",
        (conversation_id, user_id),
    ).fetchone()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy phiên hội thoại hoặc bạn không có quyền xóa.",
        )
    conn.execute("DELETE FROM ai_messages WHERE conversation_id = ? AND user_id = ?", (conversation_id, user_id))
    conn.execute("DELETE FROM ai_conversations WHERE conversation_id = ? AND user_id = ?", (conversation_id, user_id))
    conn.commit()
    return {"status": "ok", "conversation_id": conversation_id}


# =============================================================================
# MULTI-TURN CONTEXT RESOLUTION (ALWAYS RE-VALIDATED BY LIVE RBAC GATE!)
# =============================================================================

DEPT_ANAPHORA_PATTERN = re.compile(
    r"\b(?:phòng\s+(?:đó|này|kia|vừa\s+rồi|trên|đứng\s+đầu)|đơn\s+vị\s+(?:đó|này)|bộ\s+phận\s+(?:đó|này))\b",
    flags=re.IGNORECASE,
)
EMP_ANAPHORA_PATTERN = re.compile(
    r"\b(?:nhân\s+viên\s+(?:đó|này|vừa\s+rồi)|người\s+(?:đó|này|đứng\s+đầu)|bạn\s+(?:đó|này)|họ|anh\s+ấy|chị\s+ấy)\b",
    flags=re.IGNORECASE,
)
RULE_ANAPHORA_PATTERN = re.compile(
    r"\b(?:cảnh\s+báo\s+(?:đó|này|vừa\s+rồi)|quy\s+tắc\s+(?:đó|này)|lỗi\s+(?:đó|này))\b",
    flags=re.IGNORECASE,
)
PERIOD_SHIFT_FOLLOWUP_PATTERN = re.compile(
    r"^(?:còn|vậy|thế|như\s+vậy)?\s*(?:tháng|kỳ|quý|năm)\b",
    flags=re.IGNORECASE,
)
SHORT_FOLLOWUP_SUFFIX_PATTERN = re.compile(
    r"(?:thì\s+sao|ra\s+sao|như\s+thế\s+nào|thế\s+nào)\s*\??$",
    flags=re.IGNORECASE,
)


def resolve_followup_entities(
    question: str,
    entities: Dict[str, Any],
    context_state: Dict[str, Any],
) -> Tuple[Dict[str, Any], bool]:
    """Enrich extracted entities from conversation context_state for genuine follow-up questions.

    SECURITY: Resolved entities are returned to the orchestrator BEFORE the live RBAC Policy Gate runs,
    so stale or narrowed-away permissions are NEVER bypassed by conversation history!
    """
    if not context_state:
        return entities, False

    q_clean = question.strip()
    q_lower = q_clean.lower()
    used_context = False
    out = dict(entities)

    period_info = dict(out.get("period_info") or {})
    explicit_period = period_info.get("primary")
    mentioned_depts: List[str] = list(out.get("mentioned_depts") or [])
    emp_codes: List[str] = list(out.get("emp_codes") or [])
    rule_codes: List[str] = list(out.get("rule_codes") or [])

    # 1. Resolve department pronoun ("phòng đó", "đơn vị đó") — smartly respects period-indexed top department!
    if DEPT_ANAPHORA_PATTERN.search(q_lower) and not mentioned_depts:
        top_by_period: Dict[str, str] = context_state.get("top_department_by_period") or {}
        resolved_dept: Optional[str] = None
        if explicit_period and explicit_period in top_by_period:
            resolved_dept = top_by_period[explicit_period]
        else:
            resolved_dept = context_state.get("last_top_department") or context_state.get("last_department")
        if resolved_dept:
            out["mentioned_depts"] = [resolved_dept]
            out["force_self"] = False
            used_context = True

    # 2. Resolve employee pronoun ("nhân viên đó", "người đó")
    if EMP_ANAPHORA_PATTERN.search(q_lower) and not emp_codes and not out.get("target_emp"):
        resolved_emp = context_state.get("last_top_employee_id") or context_state.get("last_employee_id")
        if resolved_emp:
            out["emp_codes"] = [resolved_emp]
            out["target_emp"] = resolved_emp
            out["force_self"] = False
            used_context = True

    # 3. Resolve rule code pronoun ("cảnh báo đó", "quy tắc này")
    if RULE_ANAPHORA_PATTERN.search(q_lower) and not rule_codes:
        last_rc = context_state.get("last_rule_code")
        if last_rc:
            out["rule_codes"] = [last_rc]
            used_context = True

    # 4. Short period-shift follow-up ("Còn tháng 9 thì sao?", "Tháng 11 thì sao?", "Còn kỳ trước?")
    last_sql_intent = context_state.get("last_sql_intent")
    word_count = len(q_lower.split())
    is_period_shift = (
        bool(explicit_period)
        and last_sql_intent
        and word_count <= 9
        and (
            bool(PERIOD_SHIFT_FOLLOWUP_PATTERN.search(q_lower))
            or bool(SHORT_FOLLOWUP_SUFFIX_PATTERN.search(q_lower))
        )
        and not any(
            k in q_lower
            for k in ["liệt kê", "cảnh báo", "nghỉ phép", "quỹ phép", "quy định", "quy trình", "nhân sự", "trưởng phòng"]
        )
    )
    if is_period_shift:
        out["inherited_sql_intent"] = last_sql_intent
        if not out.get("mentioned_depts") and context_state.get("last_department"):
            out["mentioned_depts"] = [context_state["last_department"]]
        if not out.get("target_emp") and context_state.get("last_employee_id"):
            out["target_emp"] = context_state["last_employee_id"]
            out["emp_codes"] = [context_state["last_employee_id"]]
        if context_state.get("last_force_self") and not out.get("mentioned_depts") and not out.get("target_emp"):
            out["force_self"] = True
        if not out.get("rule_codes") and context_state.get("last_rule_code"):
            out["rule_codes"] = [context_state["last_rule_code"]]
        used_context = True

    # 5. Inherit last_period when asking anaphoric follow-up without stating a new period ("Top 3 của phòng đó?", "Còn nhân viên đó đi muộn mấy lần?")
    if used_context and not explicit_period and context_state.get("last_period"):
        period_info["primary"] = context_state["last_period"]
        period_info["periods"] = [context_state["last_period"]]
        period_info["explicit"] = True
        out["period_info"] = period_info

    return out, used_context


def build_updated_context_state(
    prev_state: Dict[str, Any],
    question: str,
    route_type: str,
    primary_sql_intent: Optional[str],
    entities: Dict[str, Any],
    sql_evidences: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Update structured conversation context state strictly from authorized results of the current turn."""
    state = dict(prev_state or {})
    state["turn_count"] = int(state.get("turn_count") or 0) + 1
    state["last_question"] = question[:300]
    state["last_route"] = route_type

    if primary_sql_intent:
        state["last_sql_intent"] = primary_sql_intent

    period = (entities.get("period_info") or {}).get("primary") or entities.get("effective_period")
    if period:
        state["last_period"] = period

    mentioned_depts = entities.get("mentioned_depts") or []
    if mentioned_depts:
        state["last_department"] = mentioned_depts[0]
    elif primary_sql_intent in ("compare_department_metrics", "compare_departments_full", "anomalies_by_department"):
        state["last_department"] = None

    if entities.get("target_emp"):
        state["last_employee_id"] = entities["target_emp"]
    elif primary_sql_intent in ("compare_department_metrics", "compare_departments_full", "anomalies_by_department"):
        state["last_employee_id"] = None

    state["last_force_self"] = bool(entities.get("force_self"))

    rule_codes = entities.get("rule_codes") or []
    if rule_codes:
        state["last_rule_code"] = rule_codes[0]

    # Track top department & top employee observed in authorized SQL outputs (for "phòng đó" / "người đó")
    top_by_period: Dict[str, str] = dict(state.get("top_department_by_period") or {})
    for ev in sql_evidences:
        rows = ev.get("rows") or []
        if not rows:
            continue
        first = rows[0]
        if isinstance(first, dict):
            if first.get("department_name"):
                state["last_top_department"] = str(first["department_name"])
                ev_period = ev.get("period") or period
                if ev_period:
                    top_by_period[str(ev_period)] = str(first["department_name"])
            if first.get("employee_id"):
                state["last_top_employee_id"] = str(first["employee_id"])
            elif first.get("target_code") and str(first["target_code"]).startswith("NV"):
                state["last_top_employee_id"] = str(first["target_code"])
            if first.get("rule_code") and not rule_codes:
                state["last_rule_code"] = str(first["rule_code"])

    if top_by_period:
        state["top_department_by_period"] = top_by_period

    return state
