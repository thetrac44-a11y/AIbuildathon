from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.security import AuthenticatedUser, get_db_dependency, require_permissions
from app.services.ai_assistant import answer_question, get_suggested_prompts
from app.services.ai_context_manager import (
    delete_user_conversation,
    get_user_conversation_detail,
    list_user_conversations,
)

router = APIRouter(prefix="/api/assistant", tags=["ai-assistant"])


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    conversation_id: Optional[str] = Field(default=None, max_length=64)
    active_period: Optional[str] = Field(default=None, max_length=16)


@router.post("/ask")
def ask_assistant(
    payload: AskRequest,
    current_user: AuthenticatedUser = Depends(
        require_permissions("ai.ask.self", "ai.ask.department", "ai.ask.all", "ai.strategy")
    ),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    return answer_question(
        conn,
        current_user,
        payload.question,
        conversation_id=payload.conversation_id,
        active_period=payload.active_period,
    )


@router.get("/suggestions")
def list_suggestions(
    current_user: AuthenticatedUser = Depends(
        require_permissions("ai.ask.self", "ai.ask.department", "ai.ask.all", "ai.strategy")
    ),
) -> Dict[str, Any]:
    return {
        "role": current_user.role.value,
        "suggestions": get_suggested_prompts(current_user.role),
    }


@router.get("/conversations")
def list_my_conversations(
    limit: int = Query(default=30, ge=1, le=100),
    current_user: AuthenticatedUser = Depends(
        require_permissions("ai.ask.self", "ai.ask.department", "ai.ask.all", "ai.strategy")
    ),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    """List saved AI conversation threads strictly for current_user (read-only; zero audit log created)."""
    items = list_user_conversations(conn, current_user.user_id, limit=limit)
    return {"total": len(items), "items": items}


@router.get("/conversations/{conversation_id}")
def get_my_conversation(
    conversation_id: str,
    current_user: AuthenticatedUser = Depends(
        require_permissions("ai.ask.self", "ai.ask.department", "ai.ask.all", "ai.strategy")
    ),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    """Load saved messages & responses of a conversation strictly owned by current_user (zero re-query / zero audit log)."""
    return get_user_conversation_detail(conn, current_user.user_id, conversation_id)


@router.delete("/conversations/{conversation_id}")
def delete_my_conversation(
    conversation_id: str,
    current_user: AuthenticatedUser = Depends(
        require_permissions("ai.ask.self", "ai.ask.department", "ai.ask.all", "ai.strategy")
    ),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    """Delete a conversation thread strictly owned by current_user."""
    return delete_user_conversation(conn, current_user.user_id, conversation_id)


@router.get("/history")
def list_my_chat_history(
    limit: int = Query(default=30, ge=1, le=100),
    current_user: AuthenticatedUser = Depends(
        require_permissions("ai.ask.self", "ai.ask.department", "ai.ask.all", "ai.strategy")
    ),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    """Chat history is strictly isolated to the authenticated user_id to prevent cross-user leakage."""
    rows = conn.execute(
        """
        SELECT id, asked_at, question, query_type, tool_name, sql_text, row_count, status
        FROM query_audit_log
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (current_user.user_id, limit),
    ).fetchall()
    return {"total": len(rows), "items": [dict(r) for r in rows]}
