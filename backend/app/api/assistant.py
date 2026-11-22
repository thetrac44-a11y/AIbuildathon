from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.security import AuthenticatedUser, get_current_user, get_db_dependency
from app.services.ai_assistant import answer_question, get_suggested_prompts

router = APIRouter(prefix="/api/assistant", tags=["ai-assistant"])


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)


@router.post("/ask")
def ask_assistant(
    payload: AskRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    return answer_question(conn, current_user, payload.question)


@router.get("/suggestions")
def list_suggestions(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> Dict[str, Any]:
    return {
        "role": current_user.role.value,
        "suggestions": get_suggested_prompts(current_user.role),
    }


@router.get("/history")
def list_my_chat_history(
    limit: int = Query(default=30, ge=1, le=100),
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    """Chat history is strictly isolated to the authenticated user_id to prevent cross-user leakage."""
    rows = conn.execute(
        """
        SELECT id, asked_at, question, tool_name, sql_text, row_count, status
        FROM query_audit_log
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (current_user.user_id, limit),
    ).fetchall()
    return {"total": len(rows), "items": [dict(r) for r in rows]}
