from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional

from app.core.security import AuthenticatedUser
from app.services.ai_llm_client import BaseLLMProvider
from app.services.ai_orchestrator import (
    LEAVE_STATUS_LABELS,
    LEAVE_TYPE_LABELS,
    OUT_OF_SCOPE_PATTERNS,
    PROMPT_INJECTION_PATTERNS,
    WRITE_ACTION_PATTERNS,
    answer_question_hybrid,
    get_suggested_prompts,
)


def answer_question(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    question: str,
    conversation_id: Optional[str] = None,
    active_period: Optional[str] = None,
    llm_provider_override: Optional[BaseLLMProvider] = None,
) -> Dict[str, Any]:
    """Unified AI Assistant entrypoint (Phase 3 Hybrid SQL + RAG Orchestrator; 100% backward-compatible)."""
    return answer_question_hybrid(
        conn=conn,
        user=user,
        question=question,
        conversation_id=conversation_id,
        active_period=active_period,
        llm_provider_override=llm_provider_override,
    )


__all__ = [
    "LEAVE_STATUS_LABELS",
    "LEAVE_TYPE_LABELS",
    "OUT_OF_SCOPE_PATTERNS",
    "PROMPT_INJECTION_PATTERNS",
    "WRITE_ACTION_PATTERNS",
    "answer_question",
    "get_suggested_prompts",
]
