from __future__ import annotations

import datetime
import json
import math
import time
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from app.core.security import AuthenticatedUser
from app.db.connection import is_postgres_connection
from app.services.rag_embeddings import (
    EmbeddingProvider,
    EmbeddingProviderError,
    LocalFeatureHashEmbeddingProvider,
    cosine_similarity,
    json_to_vector,
    resolve_embedding_provider,
    tokenize_vietnamese_for_rag,
    vector_to_pg_literal,
)
from app.services.rag_security import get_allowed_visibilities, scan_text_for_prompt_injection

# Evidence sufficiency thresholds calibrated on Vietnamese HR corpus (SQLite + Supabase pgvector)
# Relevant policy queries: BM25 ~35-70 (strong>=2, ratio>=0.35), Vector ~0.31-0.60
# Unrelated Vietnamese noise: BM25 <=14 (strong==0, ratio<0.25), Vector <0.19
MIN_BM25_SUFFICIENCY_SCORE = 16.0
MIN_BM25_COVERAGE_RATIO = 0.35
MIN_VECTOR_SUFFICIENCY_SCORE = 0.24
MIN_HYBRID_VECTOR_FLOOR = 0.20
RRF_K = 60.0


def _parse_json_meta(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}
    return {}


def _detect_pgvector_schema(conn: Any) -> str:
    """Detect schema where pgvector extension is installed ('extensions' on Supabase, 'public' on vanilla PG)."""
    try:
        row = conn.execute(
            """
            SELECT n.nspname AS ext_schema
            FROM pg_extension e
            JOIN pg_namespace n ON n.oid = e.extnamespace
            WHERE e.extname = 'vector'
            LIMIT 1
            """
        ).fetchone()
        if row and row["ext_schema"]:
            return str(row["ext_schema"])
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    return "extensions"


def _build_document_access_where(
    user: AuthenticatedUser,
    as_of_date: str,
    document_type: Optional[str] = None,
    pg: bool = False,
) -> Tuple[str, List[Any]]:
    """Build mandatory SQL WHERE filter enforcing RBAC visibility + active/current version + effective dates."""
    visibilities = get_allowed_visibilities(user)
    if not visibilities:
        return "1 = 0", []

    vis_placeholders = ", ".join("?" for _ in visibilities)
    where_parts = [
        "d.status = 'active'",
        "COALESCE(d.is_current, 1) = 1",
        f"COALESCE(d.visibility, 'all') IN ({vis_placeholders})",
    ]
    params: List[Any] = list(visibilities)

    if pg:
        where_parts.append("(d.effective_from IS NULL OR d.effective_from <= CAST(? AS DATE))")
        where_parts.append("(d.effective_to IS NULL OR d.effective_to >= CAST(? AS DATE))")
        params.extend([as_of_date, as_of_date])
    else:
        where_parts.append("(d.effective_from IS NULL OR d.effective_from <= ?)")
        where_parts.append("(d.effective_to IS NULL OR d.effective_to >= ?)")
        params.extend([as_of_date, as_of_date])

    if document_type:
        where_parts.append("d.document_type = ?")
        params.append(document_type)

    return " AND ".join(where_parts), params


def _fetch_candidate_chunks(
    conn: Any,
    user: AuthenticatedUser,
    as_of_date: str,
    document_type: Optional[str] = None,
    include_sqlite_embedding: bool = False,
) -> List[Dict[str, Any]]:
    pg = is_postgres_connection(conn)
    where_sql, params = _build_document_access_where(user, as_of_date, document_type=document_type, pg=pg)
    if where_sql == "1 = 0":
        return []

    emb_col = ", c.embedding_json" if (include_sqlite_embedding and not pg) else ""
    rows = conn.execute(
        f"""
        SELECT
            c.chunk_id,
            c.document_id,
            c.chunk_index,
            c.content,
            c.embedding_model,
            c.embedding_dim,
            c.metadata AS chunk_metadata,
            d.title,
            d.original_file_name,
            d.document_type,
            d.version_label,
            d.visibility,
            d.effective_from,
            d.effective_to,
            d.status
            {emb_col}
        FROM document_chunks c
        JOIN company_documents d ON d.document_id = c.document_id
        WHERE {where_sql}
        ORDER BY d.document_id ASC, c.chunk_index ASC
        """,
        params,
    ).fetchall()

    items: List[Dict[str, Any]] = []
    for r in rows:
        item = dict(r)
        meta = _parse_json_meta(item.get("chunk_metadata"))
        item["chunk_metadata"] = meta
        item["section_title"] = meta.get("section_title") or item.get("title")
        item["article_ref"] = meta.get("article_ref")
        item["page_number"] = meta.get("page_number")
        items.append(item)
    return items


class BM25Retriever:
    """Real Okapi BM25 retrieval over strictly RBAC/version/effective-date filtered RAG chunks."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b

    def search(
        self,
        candidates: List[Dict[str, Any]],
        query: str,
        top_k: int = 5,
    ) -> Tuple[List[Dict[str, Any]], float]:
        t0 = time.monotonic()
        if not candidates or not (query or "").strip():
            return [], 0.0

        q_tokens = tokenize_vietnamese_for_rag(query)
        if not q_tokens:
            return [], round((time.monotonic() - t0) * 1000.0, 2)

        q_unique = list(dict.fromkeys(q_tokens))
        doc_tokens_list: List[Counter[str]] = []
        doc_lengths: List[int] = []
        df: Counter[str] = Counter()

        for item in candidates:
            searchable = f"{item.get('title', '')} {item.get('section_title', '')} {item.get('content', '')}"
            toks = tokenize_vietnamese_for_rag(searchable)
            tf = Counter(toks)
            doc_tokens_list.append(tf)
            doc_lengths.append(max(1, len(toks)))
            for term in tf.keys():
                df[term] += 1

        n_docs = len(candidates)
        avgdl = sum(doc_lengths) / max(1, n_docs)

        scored: List[Dict[str, Any]] = []
        for idx, item in enumerate(candidates):
            tf_map = doc_tokens_list[idx]
            dl = doc_lengths[idx]
            score = 0.0
            matched_terms = 0
            matched_strong_terms = 0
            for term in q_unique:
                f = tf_map.get(term, 0)
                if f <= 0:
                    continue
                matched_terms += 1
                is_strong = term.startswith(("rule:", "__concept_", "vbg:"))
                if is_strong:
                    matched_strong_terms += 1
                idf = math.log(((n_docs - df[term] + 0.5) / (df[term] + 0.5)) + 1.0)
                num = f * (self.k1 + 1.0)
                den = f + self.k1 * (1.0 - self.b + self.b * (dl / max(1.0, avgdl)))
                weight = (
                    2.0
                    if term.startswith(("rule:", "__concept_"))
                    else (1.5 if term.startswith("vbg:") else (1.1 if term.startswith("bg:") else 1.0))
                )
                score += weight * idf * (num / den)

            if score > 0.0:
                entry = dict(item)
                entry["bm25_score"] = round(score, 4)
                entry["matched_terms"] = matched_terms
                entry["matched_strong_terms"] = matched_strong_terms
                entry["matched_ratio"] = round(matched_terms / max(1, len(q_unique)), 4)
                scored.append(entry)

        scored.sort(key=lambda x: (-x["bm25_score"], x["document_id"], x["chunk_index"]))
        elapsed_ms = round((time.monotonic() - t0) * 1000.0, 2)
        return scored[:top_k], elapsed_ms


class VectorRetriever:
    """Real dense vector cosine search using pgvector (<=>) on Supabase PostgreSQL and numpy cosine on SQLite."""

    def search(
        self,
        conn: Any,
        user: AuthenticatedUser,
        query: str,
        provider: EmbeddingProvider,
        as_of_date: str,
        top_k: int = 5,
        document_type: Optional[str] = None,
        sqlite_candidates: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[List[Dict[str, Any]], float]:
        t0 = time.monotonic()
        if not (query or "").strip():
            return [], 0.0

        query_vec = provider.embed_query(query)
        model_name = provider.model_name
        pg = is_postgres_connection(conn)

        if pg:
            where_sql, params = _build_document_access_where(user, as_of_date, document_type=document_type, pg=True)
            if where_sql == "1 = 0":
                return [], round((time.monotonic() - t0) * 1000.0, 2)

            vec_schema = _detect_pgvector_schema(conn)
            vec_lit = vector_to_pg_literal(query_vec)
            rows = conn.execute(
                f"""
                SELECT
                    c.chunk_id,
                    c.document_id,
                    c.chunk_index,
                    c.content,
                    c.embedding_model,
                    c.embedding_dim,
                    c.metadata AS chunk_metadata,
                    d.title,
                    d.original_file_name,
                    d.document_type,
                    d.version_label,
                    d.visibility,
                    d.effective_from,
                    d.effective_to,
                    d.status,
                    (1.0 - (c.embedding OPERATOR({vec_schema}.<=>) (?)::{vec_schema}.vector)) AS vector_score
                FROM public.document_chunks c
                JOIN public.company_documents d ON d.document_id = c.document_id
                WHERE {where_sql}
                  AND c.embedding IS NOT NULL
                  AND c.embedding_model = ?
                ORDER BY c.embedding OPERATOR({vec_schema}.<=>) (?)::{vec_schema}.vector ASC
                LIMIT ?
                """,
                [vec_lit, *params, model_name, vec_lit, max(1, int(top_k))],
            ).fetchall()

            results: List[Dict[str, Any]] = []
            for r in rows:
                item = dict(r)
                meta = _parse_json_meta(item.get("chunk_metadata"))
                item["chunk_metadata"] = meta
                item["section_title"] = meta.get("section_title") or item.get("title")
                item["article_ref"] = meta.get("article_ref")
                item["page_number"] = meta.get("page_number")
                item["vector_score"] = round(float(item.get("vector_score") or 0.0), 4)
                results.append(item)
            elapsed_ms = round((time.monotonic() - t0) * 1000.0, 2)
            return results, elapsed_ms

        # SQLite path: exact numpy cosine similarity on stored embedding_json matching embedding_model
        candidates = (
            sqlite_candidates
            if sqlite_candidates is not None
            else _fetch_candidate_chunks(
                conn, user, as_of_date, document_type=document_type, include_sqlite_embedding=True
            )
        )
        scored: List[Dict[str, Any]] = []
        for item in candidates:
            if item.get("embedding_model") != model_name:
                continue
            chunk_vec = json_to_vector(item.get("embedding_json"))
            if chunk_vec is None or chunk_vec.size != len(query_vec):
                continue
            sim = cosine_similarity(query_vec, chunk_vec)
            entry = {k: v for k, v in item.items() if k != "embedding_json"}
            entry["vector_score"] = round(sim, 4)
            scored.append(entry)

        scored.sort(key=lambda x: (-x["vector_score"], x["document_id"], x["chunk_index"]))
        elapsed_ms = round((time.monotonic() - t0) * 1000.0, 2)
        return scored[:top_k], elapsed_ms


class HybridRetriever:
    """Combines BM25 + Vector Retrieval via Reciprocal Rank Fusion (RRF) with Injection Sanitization & Sufficiency Gate."""

    def __init__(self) -> None:
        self.bm25 = BM25Retriever()
        self.vector = VectorRetriever()

    def retrieve(
        self,
        conn: Any,
        user: AuthenticatedUser,
        query: str,
        mode: str = "hybrid",
        top_k: int = 5,
        as_of_date: Optional[str] = None,
        document_type: Optional[str] = None,
        allow_offline_fallback: bool = True,
        override_embedding_provider: Optional[str] = None,
    ) -> Dict[str, Any]:
        total_start = time.monotonic()
        eff_date = as_of_date or datetime.date.today().isoformat()
        eff_mode = mode.lower().strip() if mode else "hybrid"
        if eff_mode not in ("bm25", "vector", "hybrid"):
            eff_mode = "hybrid"

        visibilities = get_allowed_visibilities(user)
        if not visibilities:
            return {
                "status": "blocked",
                "mode": eff_mode,
                "sufficient_evidence": False,
                "reason": "Tài khoản hiện tại không được cấp quyền truy xuất kho tri thức RAG nghiệp vụ.",
                "embedding_model": None,
                "offline_fallback": False,
                "chunks": [],
                "quarantined_injections": 0,
                "metrics": {"bm25_ms": 0.0, "vector_ms": 0.0, "total_ms": 0.0, "candidate_count": 0},
            }

        pg = is_postgres_connection(conn)
        fetch_k = max(top_k * 3, 12)
        candidates: List[Dict[str, Any]] = []
        if eff_mode in ("bm25", "hybrid") or not pg:
            candidates = _fetch_candidate_chunks(
                conn,
                user,
                as_of_date=eff_date,
                document_type=document_type,
                include_sqlite_embedding=(not pg and eff_mode in ("vector", "hybrid")),
            )

        bm25_hits: List[Dict[str, Any]] = []
        vec_hits: List[Dict[str, Any]] = []
        bm25_ms = 0.0
        vector_ms = 0.0
        embedding_model: Optional[str] = None
        offline_fallback = False
        fallback_reason: Optional[str] = None

        if eff_mode in ("bm25", "hybrid"):
            bm25_hits, bm25_ms = self.bm25.search(candidates, query, top_k=fetch_k)

        if eff_mode in ("vector", "hybrid"):
            emb_res = resolve_embedding_provider(
                conn,
                allow_offline_fallback=allow_offline_fallback,
                override_provider=override_embedding_provider,
            )
            provider = emb_res.provider
            offline_fallback = emb_res.offline_fallback
            fallback_reason = emb_res.fallback_reason
            try:
                vec_hits, vector_ms = self.vector.search(
                    conn,
                    user,
                    query,
                    provider=provider,
                    as_of_date=eff_date,
                    top_k=fetch_k,
                    document_type=document_type,
                    sqlite_candidates=candidates if not pg else None,
                )
                embedding_model = provider.model_name
            except EmbeddingProviderError as exc:
                if not allow_offline_fallback:
                    raise
                local_prov = LocalFeatureHashEmbeddingProvider()
                offline_fallback = True
                fallback_reason = str(exc)
                vec_hits, vector_ms = self.vector.search(
                    conn,
                    user,
                    query,
                    provider=local_prov,
                    as_of_date=eff_date,
                    top_k=fetch_k,
                    document_type=document_type,
                    sqlite_candidates=candidates if not pg else None,
                )
                embedding_model = local_prov.model_name

        # Merge results according to retrieval mode
        merged_by_id: Dict[int, Dict[str, Any]] = {}
        bm25_rank: Dict[int, int] = {}
        vec_rank: Dict[int, int] = {}

        for rank, h in enumerate(bm25_hits, start=1):
            cid = int(h["chunk_id"])
            bm25_rank[cid] = rank
            merged_by_id[cid] = dict(h)
            merged_by_id[cid]["bm25_score"] = h["bm25_score"]
            merged_by_id[cid].setdefault("vector_score", 0.0)

        for rank, h in enumerate(vec_hits, start=1):
            cid = int(h["chunk_id"])
            vec_rank[cid] = rank
            if cid not in merged_by_id:
                merged_by_id[cid] = dict(h)
                merged_by_id[cid].setdefault("bm25_score", 0.0)
            merged_by_id[cid]["vector_score"] = h["vector_score"]

        ranked_items: List[Dict[str, Any]] = []
        for cid, item in merged_by_id.items():
            b_score = float(item.get("bm25_score") or 0.0)
            v_score = float(item.get("vector_score") or 0.0)

            if eff_mode == "bm25":
                h_score = b_score
            elif eff_mode == "vector":
                h_score = v_score
            else:
                # Reciprocal Rank Fusion weighted slightly toward lexical BM25 for exact policy terms + dense semantic signal
                rrf = 0.0
                if cid in bm25_rank:
                    rrf += 0.55 / (RRF_K + bm25_rank[cid])
                if cid in vec_rank:
                    rrf += 0.45 / (RRF_K + vec_rank[cid])
                # Normalize RRF into readable [0..1] scale relative to theoretical top-1 rank
                max_rrf = 1.0 / (RRF_K + 1.0)
                h_score = round(min(1.0, (rrf / max_rrf) * 0.65 + min(1.0, max(0.0, v_score)) * 0.35), 4)

            item["bm25_score"] = round(b_score, 4)
            item["vector_score"] = round(v_score, 4)
            item["hybrid_score"] = round(h_score, 4)
            ranked_items.append(item)

        if eff_mode == "bm25":
            ranked_items.sort(key=lambda x: (-x["bm25_score"], x["document_id"], x["chunk_index"]))
        elif eff_mode == "vector":
            ranked_items.sort(key=lambda x: (-x["vector_score"], x["document_id"], x["chunk_index"]))
        else:
            ranked_items.sort(key=lambda x: (-x["hybrid_score"], -x["bm25_score"], -x["vector_score"]))

        # Prompt-injection sanitization & quarantine BEFORE sufficiency decision
        clean_chunks: List[Dict[str, Any]] = []
        quarantined_count = 0
        for item in ranked_items:
            inj = scan_text_for_prompt_injection(str(item.get("content") or ""))
            if inj["quarantined"]:
                quarantined_count += 1
                continue
            item["sanitized_content"] = inj["sanitized_text"]
            item["injection_flagged"] = inj["flagged"]
            clean_chunks.append(item)
            if len(clean_chunks) >= top_k:
                break

        # Strict Evidence Sufficiency Gate (refuse incidental single-syllable collisions & unrelated noise)
        sufficient = False
        if clean_chunks:
            top = clean_chunks[0]
            b_sc = float(top.get("bm25_score") or 0.0)
            v_sc = float(top.get("vector_score") or 0.0)
            m_ratio = float(top.get("matched_ratio") or 0.0)
            strong = int(top.get("matched_strong_terms") or 0)
            bm25_strong_ok = (
                (b_sc >= MIN_BM25_SUFFICIENCY_SCORE and strong >= 1)
                or (b_sc >= 9.0 and m_ratio >= MIN_BM25_COVERAGE_RATIO)
            )

            if eff_mode == "bm25":
                sufficient = bm25_strong_ok
            elif eff_mode == "vector":
                sufficient = v_sc >= MIN_VECTOR_SUFFICIENCY_SCORE
            else:
                # Hybrid requires either solid vector similarity OR strong lexical phrase/concept alignment above vector floor
                sufficient = (
                    v_sc >= MIN_VECTOR_SUFFICIENCY_SCORE
                    or (bm25_strong_ok and (v_sc >= MIN_HYBRID_VECTOR_FLOOR or strong >= 2))
                )

        if not sufficient:
            clean_chunks = []

        total_ms = round((time.monotonic() - total_start) * 1000.0, 2)
        return {
            "status": "sufficient" if sufficient else "insufficient_evidence",
            "mode": eff_mode,
            "sufficient_evidence": sufficient,
            "reason": (
                None
                if sufficient
                else "Kho tài liệu nội bộ hiện hành chưa có đủ căn cứ phù hợp để trả lời câu hỏi này."
            ),
            "embedding_model": embedding_model,
            "offline_fallback": offline_fallback,
            "fallback_reason": fallback_reason,
            "chunks": clean_chunks,
            "quarantined_injections": quarantined_count,
            "metrics": {
                "bm25_ms": bm25_ms,
                "vector_ms": vector_ms,
                "total_ms": total_ms,
                "candidate_count": len(candidates) if candidates else len(vec_hits),
            },
        }
