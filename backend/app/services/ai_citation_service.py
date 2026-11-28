from __future__ import annotations

from typing import Any, Dict, List, Optional


def build_rag_citations(
    chunks: List[Dict[str, Any]],
    retrieval_mode: str = "hybrid",
    max_excerpt_chars: int = 320,
) -> List[Dict[str, Any]]:
    """Build strictly grounded RAG citations ONLY from verified, sanitized retrieved chunks."""
    citations: List[Dict[str, Any]] = []
    for idx, ch in enumerate(chunks, start=1):
        raw_excerpt = str(ch.get("sanitized_content") or ch.get("content") or "").strip()
        if not raw_excerpt:
            continue
        excerpt = (
            raw_excerpt[:max_excerpt_chars].rstrip() + "..."
            if len(raw_excerpt) > max_excerpt_chars
            else raw_excerpt
        )
        citations.append(
            {
                "type": "rag",
                "citation_id": f"DOC-{idx}",
                "document_id": int(ch["document_id"]),
                "title": str(ch.get("title") or "Tài liệu nội bộ"),
                "original_file_name": str(ch.get("original_file_name") or ""),
                "document_type": str(ch.get("document_type") or "policy"),
                "version_label": str(ch.get("version_label") or "v1.0"),
                "effective_from": ch.get("effective_from"),
                "effective_to": ch.get("effective_to"),
                "section_title": str(ch.get("section_title") or ch.get("title") or ""),
                "article_ref": ch.get("article_ref"),
                "page_number": ch.get("page_number"),
                "chunk_id": int(ch["chunk_id"]),
                "chunk_index": int(ch.get("chunk_index", 0)),
                "excerpt": excerpt,
                "retrieval_mode": retrieval_mode,
                "scores": {
                    "bm25": round(float(ch.get("bm25_score") or 0.0), 4),
                    "vector": round(float(ch.get("vector_score") or 0.0), 4),
                    "hybrid": round(float(ch.get("hybrid_score") or 0.0), 4),
                },
            }
        )
    return citations


def build_sql_citation(
    source_label: str,
    scope_label: str,
    tool_name: str,
    record_count: int,
    period: Optional[str] = None,
    verified: bool = True,
) -> Dict[str, Any]:
    """Build business-friendly SQL evidence citation (shared with Phase 3 Hybrid Orchestrator)."""
    return {
        "type": "sql",
        "source_label": source_label,
        "scope_label": scope_label,
        "period": period,
        "record_count": int(record_count),
        "tool_name": tool_name,
        "verified": bool(verified),
    }


def format_rag_citations_markdown(citations: List[Dict[str, Any]]) -> str:
    """Format verified RAG citations into concise Vietnamese references."""
    if not citations:
        return ""
    lines: List[str] = ["Nguồn trích dẫn tài liệu hiện hành:"]
    for c in citations:
        parts = [f"**{c['title']}** ({c['version_label']})"]
        if c.get("section_title") and c["section_title"] != c["title"]:
            parts.append(c["section_title"])
        if c.get("page_number"):
            parts.append(f"Trang {c['page_number']}")
        lines.append(f"- [{c['citation_id']}] " + " · ".join(parts))
    return "\n".join(lines)
