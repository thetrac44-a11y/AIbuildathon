from __future__ import annotations

import datetime
import json
import uuid
from typing import Any, Dict, List, Optional

from app.core.security import AuthenticatedUser, write_activity_log
from app.db.connection import is_postgres_connection
from app.services.ai_citation_service import build_rag_citations, format_rag_citations_markdown
from app.services.rag_chunker import DEFAULT_CHUNK_OVERLAP, chunk_document_text
from app.services.rag_document_processor import (
    ExtractedDocument,
    RagDocumentProcessingError,
    prepare_raw_text_document,
    validate_and_extract_file,
)
from app.services.rag_embeddings import (
    EmbeddingProviderError,
    read_embedding_settings,
    resolve_embedding_provider,
    vector_to_json,
    vector_to_pg_literal,
)
from app.services.rag_retriever import HybridRetriever, _detect_pgvector_schema, _parse_json_meta
from app.services.rag_seed_content import BASELINE_RAG_POLICY_CONTENT
from app.services.rag_security import VALID_DOC_VISIBILITIES, wrap_untrusted_rag_context

_RETRIEVER = HybridRetriever()


def _validate_iso_date(val: Optional[str], field_name: str) -> Optional[str]:
    if val is None or not str(val).strip():
        return None
    s = str(val).strip()[:10]
    try:
        datetime.date.fromisoformat(s)
        return s
    except ValueError as exc:
        raise RagDocumentProcessingError(f"Định dạng ngày {field_name} không hợp lệ (yêu cầu YYYY-MM-DD).") from exc


def _validate_visibility(visibility: Optional[str]) -> str:
    vis = (visibility or "all").strip().lower()
    if vis not in VALID_DOC_VISIBILITIES:
        raise RagDocumentProcessingError(
            f"Phạm vi truy cập tài liệu '{vis}' không hợp lệ. Chỉ chấp nhận: {', '.join(VALID_DOC_VISIBILITIES)}."
        )
    return vis


def _insert_indexed_chunks(
    conn: Any,
    doc_id: int,
    text: str,
    doc_meta: Dict[str, Any],
    allow_offline_fallback: bool = True,
    override_embedding_provider: Optional[str] = None,
) -> Dict[str, Any]:
    """Chunk, scan prompt injection, compute real embeddings, and persist document_chunks atomically."""
    emb_cfg = read_embedding_settings(conn)
    chunk_size = int(emb_cfg.get("chunk_size", 600))
    chunks = chunk_document_text(text, chunk_size=chunk_size, chunk_overlap=DEFAULT_CHUNK_OVERLAP, doc_meta=doc_meta)
    if not chunks:
        raise RagDocumentProcessingError("Không thể tách được đoạn nội dung hợp lệ từ tài liệu.")

    emb_res = resolve_embedding_provider(
        conn,
        allow_offline_fallback=allow_offline_fallback,
        override_provider=override_embedding_provider,
    )
    provider = emb_res.provider
    offline_fallback = emb_res.offline_fallback
    fallback_reason = emb_res.fallback_reason

    from app.services.rag_security import scan_text_for_prompt_injection

    # Embed sanitized text for injection-flagged chunks so attacker directives can NEVER poison vector search!
    texts_to_embed: List[str] = []
    for c in chunks:
        if c.metadata.get("injection_flagged"):
            san = scan_text_for_prompt_injection(c.content)["sanitized_text"]
            texts_to_embed.append(san if san else c.content)
        else:
            texts_to_embed.append(c.content)

    try:
        vectors = provider.embed_texts(texts_to_embed)
    except EmbeddingProviderError as exc:
        if not allow_offline_fallback:
            raise
        from app.services.rag_embeddings import LocalFeatureHashEmbeddingProvider

        provider = LocalFeatureHashEmbeddingProvider()
        offline_fallback = True
        fallback_reason = str(exc)
        vectors = provider.embed_texts(texts_to_embed)

    if len(vectors) != len(chunks) or any(not v for v in vectors):
        raise EmbeddingProviderError("Số lượng hoặc dữ liệu vector embedding trả về không đầy đủ.")

    pg = is_postgres_connection(conn)
    vec_schema = _detect_pgvector_schema(conn) if pg else ""
    conn.execute("DELETE FROM document_chunks WHERE document_id = ?", (doc_id,))

    flagged_count = 0
    quarantined_count = 0
    dim = len(vectors[0])

    for chunk, vec in zip(chunks, vectors):
        if chunk.metadata.get("injection_flagged"):
            flagged_count += 1
        if chunk.metadata.get("quarantined"):
            quarantined_count += 1
        c_meta_json = json.dumps(chunk.metadata, ensure_ascii=False)
        if pg:
            vec_lit = vector_to_pg_literal(vec)
            conn.execute(
                f"""
                INSERT INTO public.document_chunks (
                    document_id, chunk_index, content, embedding, embedding_model, embedding_dim, metadata
                ) VALUES (?, ?, ?, (?)::{vec_schema}.vector, ?, ?, ?::jsonb)
                """,
                (doc_id, chunk.chunk_index, chunk.content, vec_lit, provider.model_name, dim, c_meta_json),
            )
        else:
            vec_json = vector_to_json(vec)
            conn.execute(
                """
                INSERT INTO document_chunks (
                    document_id, chunk_index, content, embedding_model, embedding_json, embedding_dim, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (doc_id, chunk.chunk_index, chunk.content, provider.model_name, vec_json, dim, c_meta_json),
            )

    return {
        "chunk_count": len(chunks),
        "embedding_model": provider.model_name,
        "embedding_dim": dim,
        "chunk_size_used": chunk_size,
        "offline_fallback": offline_fallback,
        "fallback_reason": fallback_reason,
        "injection_flagged_chunks": flagged_count,
        "quarantined_chunks": quarantined_count,
    }


def ingest_rag_document(
    conn: Any,
    actor_user_id: Optional[str],
    title: str,
    original_file_name: str,
    document_type: str = "policy",
    version_label: Optional[str] = "v1.0",
    content: Optional[str] = None,
    raw_bytes: Optional[bytes] = None,
    visibility: str = "all",
    effective_from: Optional[str] = None,
    effective_to: Optional[str] = None,
    supersedes_document_id: Optional[int] = None,
    allow_offline_fallback: bool = True,
    override_embedding_provider: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate, extract, version, chunk, embed, and index a RAG document honestly (sets status='failed' on error)."""
    clean_title = (title or "").strip()
    if len(clean_title) < 2:
        raise RagDocumentProcessingError("Tiêu đề tài liệu phải có tối thiểu 2 ký tự.")

    vis = _validate_visibility(visibility)
    eff_from = _validate_iso_date(effective_from, "effective_from")
    eff_to = _validate_iso_date(effective_to, "effective_to")
    if eff_from and eff_to and eff_to < eff_from:
        raise RagDocumentProcessingError("Ngày hết hiệu lực (effective_to) phải lớn hơn hoặc bằng ngày bắt đầu (effective_from).")

    if raw_bytes is not None:
        extracted: ExtractedDocument = validate_and_extract_file(original_file_name, raw_bytes)
    else:
        extracted = prepare_raw_text_document(original_file_name, content or "")

    # Verify supersedes_document_id exists if provided
    if supersedes_document_id is not None:
        prev_doc = conn.execute(
            "SELECT document_id, title, version_label FROM company_documents WHERE document_id = ?",
            (supersedes_document_id,),
        ).fetchone()
        if not prev_doc:
            raise RagDocumentProcessingError(f"Không tìm thấy tài liệu phiên bản trước (#{supersedes_document_id}).")

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    storage_path = f"policies/{uuid.uuid4().hex[:8]}_{extracted.original_file_name}"
    init_meta = json.dumps(
        {**extracted.metadata, "indexing_state": "processing"},
        ensure_ascii=False,
    )
    pg = is_postgres_connection(conn)

    # Step 1: Insert document initially with status='processing' (NEVER mark 'active' before indexing completes!)
    if pg:
        cur = conn.execute(
            """
            INSERT INTO public.company_documents (
                title, original_file_name, storage_bucket, storage_path, document_type,
                version_label, status, checksum_sha256, uploaded_by_user_id, metadata,
                source_content, visibility, effective_from, effective_to, is_current, supersedes_document_id
            ) VALUES (?, ?, 'hr-documents', ?, ?, ?, 'processing', ?, ?, ?::jsonb, ?, ?, CAST(? AS DATE), CAST(? AS DATE), 1, ?)
            """,
            (
                clean_title,
                extracted.original_file_name,
                storage_path,
                document_type.strip(),
                version_label or "v1.0",
                extracted.checksum_sha256,
                actor_user_id,
                init_meta,
                extracted.text,
                vis,
                eff_from,
                eff_to,
                supersedes_document_id,
            ),
        )
    else:
        cur = conn.execute(
            """
            INSERT INTO company_documents (
                title, original_file_name, storage_bucket, storage_path, document_type,
                version_label, status, checksum_sha256, uploaded_by_user_id, metadata,
                source_content, visibility, effective_from, effective_to, is_current, supersedes_document_id
            ) VALUES (?, ?, 'hr-documents', ?, ?, ?, 'processing', ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                clean_title,
                extracted.original_file_name,
                storage_path,
                document_type.strip(),
                version_label or "v1.0",
                extracted.checksum_sha256,
                actor_user_id,
                init_meta,
                extracted.text,
                vis,
                eff_from,
                eff_to,
                supersedes_document_id,
            ),
        )
    doc_id = int(cur.lastrowid)

    # Step 2: Run real chunking + injection scan + real embedding + persistence
    try:
        idx_stats = _insert_indexed_chunks(
            conn,
            doc_id=doc_id,
            text=extracted.text,
            doc_meta={
                "title": clean_title,
                "version_label": version_label or "v1.0",
                "document_type": document_type.strip(),
                "visibility": vis,
                "effective_from": eff_from,
                "effective_to": eff_to,
            },
            allow_offline_fallback=allow_offline_fallback,
            override_embedding_provider=override_embedding_provider,
        )
    except Exception as exc:
        # Honest failure handling: persist status='failed' with explicit error message instead of faking success
        fail_meta = json.dumps(
            {**extracted.metadata, "indexing_state": "failed", "error": str(exc)[:400]},
            ensure_ascii=False,
        )
        if pg:
            conn.execute(
                "UPDATE public.company_documents SET status = 'failed', is_current = 0, metadata = ?::jsonb WHERE document_id = ?",
                (fail_meta, doc_id),
            )
        else:
            conn.execute(
                "UPDATE company_documents SET status = 'failed', is_current = 0, metadata = ? WHERE document_id = ?",
                (fail_meta, doc_id),
            )
        conn.commit()
        raise

    # Step 3: Archive superseded version cleanly (NEVER delete historical policy records!)
    if supersedes_document_id is not None:
        conn.execute(
            "UPDATE company_documents SET status = 'archived', is_current = 0 WHERE document_id = ?",
            (supersedes_document_id,),
        )

    final_meta = json.dumps(
        {
            **extracted.metadata,
            "indexing_state": "indexed",
            "chunks_indexed": idx_stats["chunk_count"],
            "embedding_model": idx_stats["embedding_model"],
            "embedding_dim": idx_stats["embedding_dim"],
            "chunk_size_used": idx_stats["chunk_size_used"],
            "offline_fallback": idx_stats["offline_fallback"],
            "injection_flagged_chunks": idx_stats["injection_flagged_chunks"],
            "quarantined_chunks": idx_stats["quarantined_chunks"],
        },
        ensure_ascii=False,
    )
    if pg:
        conn.execute(
            "UPDATE public.company_documents SET status = 'active', processed_at = ?, metadata = ?::jsonb WHERE document_id = ?",
            (now_str, final_meta, doc_id),
        )
    else:
        conn.execute(
            "UPDATE company_documents SET status = 'active', processed_at = ?, metadata = ? WHERE document_id = ?",
            (now_str, final_meta, doc_id),
        )

    if actor_user_id:
        write_activity_log(
            conn,
            actor_user_id=actor_user_id,
            action="upload_rag_document",
            entity_type="company_document",
            entity_id=str(doc_id),
            after_obj={
                "title": clean_title,
                "file": extracted.original_file_name,
                "version_label": version_label or "v1.0",
                "visibility": vis,
                "chunks": idx_stats["chunk_count"],
                "embedding_model": idx_stats["embedding_model"],
                "supersedes_document_id": supersedes_document_id,
            },
        )
    conn.commit()

    return {
        "status": "ok",
        "document_id": doc_id,
        "title": clean_title,
        "original_file_name": extracted.original_file_name,
        "version_label": version_label or "v1.0",
        "visibility": vis,
        "effective_from": eff_from,
        "effective_to": eff_to,
        "supersedes_document_id": supersedes_document_id,
        "checksum_sha256": extracted.checksum_sha256,
        **idx_stats,
    }


def reindex_rag_document_real(
    conn: Any,
    doc_id: int,
    actor_user_id: Optional[str] = None,
    allow_offline_fallback: bool = True,
    override_embedding_provider: Optional[str] = None,
) -> Dict[str, Any]:
    """Perform a REAL re-index: re-chunk from source_content, re-scan injection, recompute embeddings, update DB."""
    doc = conn.execute("SELECT * FROM company_documents WHERE document_id = ?", (doc_id,)).fetchone()
    if not doc:
        raise KeyError(f"Không tìm thấy tài liệu RAG #{doc_id}.")

    doc_dict = dict(doc)
    source_text = (doc_dict.get("source_content") or "").strip()
    if not source_text:
        # Backward-compat reconstruction for legacy rows uploaded before Phase 2 source_content column
        old_chunks = conn.execute(
            "SELECT content FROM document_chunks WHERE document_id = ? ORDER BY chunk_index ASC",
            (doc_id,),
        ).fetchall()
        source_text = "\n\n".join(str(r["content"]) for r in old_chunks if r["content"]).strip()

    if len(source_text) < 10:
        raise RagDocumentProcessingError(
            f"Tài liệu #{doc_id} không có nội dung nguồn để thực hiện re-index."
        )

    pg = is_postgres_connection(conn)
    prev_status = doc_dict.get("status") or "active"
    existing_meta = _parse_json_meta(doc_dict.get("metadata"))
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute("UPDATE company_documents SET status = 'processing' WHERE document_id = ?", (doc_id,))

    try:
        idx_stats = _insert_indexed_chunks(
            conn,
            doc_id=doc_id,
            text=source_text,
            doc_meta={
                "title": doc_dict["title"],
                "version_label": doc_dict.get("version_label") or "v1.0",
                "document_type": doc_dict.get("document_type") or "policy",
                "visibility": doc_dict.get("visibility") or "all",
                "effective_from": doc_dict.get("effective_from"),
                "effective_to": doc_dict.get("effective_to"),
            },
            allow_offline_fallback=allow_offline_fallback,
            override_embedding_provider=override_embedding_provider,
        )
    except Exception as exc:
        fail_meta = json.dumps({**existing_meta, "indexing_state": "failed", "error": str(exc)[:400]}, ensure_ascii=False)
        if pg:
            conn.execute(
                "UPDATE public.company_documents SET status = 'failed', metadata = ?::jsonb WHERE document_id = ?",
                (fail_meta, doc_id),
            )
        else:
            conn.execute(
                "UPDATE company_documents SET status = 'failed', metadata = ? WHERE document_id = ?",
                (fail_meta, doc_id),
            )
        conn.commit()
        raise

    new_status = "archived" if prev_status == "archived" else "active"
    new_meta = json.dumps(
        {
            **existing_meta,
            "indexing_state": "indexed",
            "chunks_indexed": idx_stats["chunk_count"],
            "embedding_model": idx_stats["embedding_model"],
            "embedding_dim": idx_stats["embedding_dim"],
            "chunk_size_used": idx_stats["chunk_size_used"],
            "offline_fallback": idx_stats["offline_fallback"],
            "injection_flagged_chunks": idx_stats["injection_flagged_chunks"],
            "quarantined_chunks": idx_stats["quarantined_chunks"],
            "last_reindexed_at": now_str,
        },
        ensure_ascii=False,
    )
    if pg:
        conn.execute(
            """
            UPDATE public.company_documents
            SET status = ?, processed_at = ?, source_content = ?, metadata = ?::jsonb
            WHERE document_id = ?
            """,
            (new_status, now_str, source_text, new_meta, doc_id),
        )
    else:
        conn.execute(
            """
            UPDATE company_documents
            SET status = ?, processed_at = ?, source_content = ?, metadata = ?
            WHERE document_id = ?
            """,
            (new_status, now_str, source_text, new_meta, doc_id),
        )

    if actor_user_id:
        write_activity_log(
            conn,
            actor_user_id=actor_user_id,
            action="reindex_rag_document",
            entity_type="company_document",
            entity_id=str(doc_id),
            after_obj={
                "title": doc_dict["title"],
                "chunk_count": idx_stats["chunk_count"],
                "embedding_model": idx_stats["embedding_model"],
                "processed_at": now_str,
            },
        )
    conn.commit()

    return {
        "status": "ok",
        "document_id": doc_id,
        "document_status": new_status,
        "processed_at": now_str,
        **idx_stats,
    }


def archive_rag_document(
    conn: Any,
    doc_id: int,
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Archive a document non-destructively so it is excluded from active policy retrieval."""
    doc = conn.execute(
        "SELECT document_id, title, version_label, status FROM company_documents WHERE document_id = ?",
        (doc_id,),
    ).fetchone()
    if not doc:
        raise KeyError(f"Không tìm thấy tài liệu RAG #{doc_id}.")

    conn.execute(
        "UPDATE company_documents SET status = 'archived', is_current = 0 WHERE document_id = ?",
        (doc_id,),
    )
    if actor_user_id:
        write_activity_log(
            conn,
            actor_user_id=actor_user_id,
            action="archive_rag_document",
            entity_type="company_document",
            entity_id=str(doc_id),
            before_obj={"status": doc["status"]},
            after_obj={"status": "archived", "is_current": 0},
        )
    conn.commit()
    return {"status": "ok", "document_id": doc_id, "new_status": "archived"}


def upgrade_placeholder_seed_documents(conn: Any) -> Dict[str, Any]:
    """Non-destructively upgrade ONLY the 3 stub seed documents (never touches real user-uploaded documents!)."""
    upgraded: List[Dict[str, Any]] = []
    skipped: List[str] = []
    pg = is_postgres_connection(conn)

    for spath, (eff_from, full_markdown) in BASELINE_RAG_POLICY_CONTENT.items():
        doc = conn.execute(
            "SELECT document_id, title, source_content, version_label FROM company_documents WHERE storage_path = ?",
            (spath,),
        ).fetchone()
        if not doc:
            continue
        doc_id = int(doc["document_id"])
        existing_chunks = conn.execute(
            "SELECT chunk_id, content, embedding_model, embedding_dim FROM document_chunks WHERE document_id = ? ORDER BY chunk_index ASC",
            (doc_id,),
        ).fetchall()

        is_stub = (
            not (doc["source_content"] or "").strip()
            and (
                len(existing_chunks) == 0
                or (
                    len(existing_chunks) == 1
                    and len(str(existing_chunks[0]["content"] or "")) < 220
                    and "đã được nạp vào kho tri thức RAG" in str(existing_chunks[0]["content"] or "")
                )
            )
        )
        missing_vectors = any(r["embedding_dim"] is None for r in existing_chunks)

        if is_stub:
            if pg:
                conn.execute(
                    """
                    UPDATE public.company_documents
                    SET source_content = ?, effective_from = COALESCE(effective_from, CAST(? AS DATE)),
                        visibility = COALESCE(visibility, 'all'), is_current = 1
                    WHERE document_id = ?
                    """,
                    (full_markdown.strip(), eff_from, doc_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE company_documents
                    SET source_content = ?, effective_from = COALESCE(effective_from, ?),
                        visibility = COALESCE(visibility, 'all'), is_current = 1
                    WHERE document_id = ?
                    """,
                    (full_markdown.strip(), eff_from, doc_id),
                )
            res = reindex_rag_document_real(conn, doc_id, actor_user_id=None)
            upgraded.append(
                {
                    "document_id": doc_id,
                    "title": doc["title"],
                    "chunk_count": res["chunk_count"],
                    "embedding_model": res["embedding_model"],
                }
            )
        elif missing_vectors and (doc["source_content"] or "").strip():
            res = reindex_rag_document_real(conn, doc_id, actor_user_id=None)
            upgraded.append(
                {
                    "document_id": doc_id,
                    "title": doc["title"],
                    "chunk_count": res["chunk_count"],
                    "embedding_model": res["embedding_model"],
                }
            )
        else:
            skipped.append(spath)

    return {"upgraded": upgraded, "skipped": skipped}


def query_rag_knowledge(
    conn: Any,
    user: AuthenticatedUser,
    question: str,
    mode: str = "hybrid",
    top_k: int = 5,
    as_of_date: Optional[str] = None,
    document_type: Optional[str] = None,
    allow_offline_fallback: bool = True,
    override_embedding_provider: Optional[str] = None,
) -> Dict[str, Any]:
    """Phase 2 RAG Service interface (strictly fault-isolated & ready for Phase 3 Hybrid Orchestrator).

    Guarantees:
    - Never throws unhandled exceptions into SQL Intelligence when called with fault isolation.
    - Enforces document RBAC visibility, active/current version, and effective dates.
    - Sanitizes/quarantines prompt-injection content inside documents.
    - Refuses to fabricate an answer when retrieval has insufficient evidence.
    """
    try:
        ret = _RETRIEVER.retrieve(
            conn=conn,
            user=user,
            query=question,
            mode=mode,
            top_k=max(1, min(int(top_k), 15)),
            as_of_date=as_of_date,
            document_type=document_type,
            allow_offline_fallback=allow_offline_fallback,
            override_embedding_provider=override_embedding_provider,
        )
    except Exception as exc:
        if is_postgres_connection(conn):
            try:
                conn.rollback()
            except Exception:
                pass
        return {
            "status": "error",
            "mode": mode,
            "sufficient_evidence": False,
            "answer": "Hệ thống tra cứu tài liệu RAG đang gặp lỗi tạm thời; dữ liệu SQL chấm công vẫn hoạt động bình thường.",
            "error_detail": str(exc),
            "embedding_model": None,
            "offline_fallback": False,
            "chunks": [],
            "citations": [],
            "untrusted_context_block": "",
            "quarantined_injections": 0,
            "metrics": {"bm25_ms": 0.0, "vector_ms": 0.0, "total_ms": 0.0, "candidate_count": 0},
        }

    if ret["status"] == "blocked":
        return {
            **ret,
            "answer": ret["reason"],
            "citations": [],
            "untrusted_context_block": "",
        }

    if not ret["sufficient_evidence"]:
        return {
            **ret,
            "answer": ret["reason"],
            "citations": [],
            "untrusted_context_block": "",
        }

    chunks = ret["chunks"]
    citations = build_rag_citations(chunks, retrieval_mode=ret["mode"])
    context_block = wrap_untrusted_rag_context(chunks)

    # Deterministic grounded policy summary directly from top sanitized chunks (zero LLM hallucination)
    excerpt_lines: List[str] = []
    for idx, ch in enumerate(chunks[:3], start=1):
        sec = ch.get("section_title") or ch.get("title")
        body = str(ch.get("sanitized_content") or ch.get("content") or "").strip()
        excerpt_lines.append(f"- **[DOC-{idx}] {ch['title']} ({ch.get('version_label') or 'v1.0'}) — {sec}:**\n  {body}")

    cit_footer = format_rag_citations_markdown(citations[:3])
    grounded_answer = (
        "Căn cứ tài liệu nội bộ hiện hành:\n\n"
        + "\n\n".join(excerpt_lines)
        + (f"\n\n{cit_footer}" if cit_footer else "")
    )

    return {
        **ret,
        "answer": grounded_answer,
        "citations": citations,
        "untrusted_context_block": context_block,
    }
