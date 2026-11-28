from __future__ import annotations

import hashlib
import json
import math
import os
import re
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx
import numpy as np

from app.db.connection import is_postgres_connection
from app.services.ai_entities import strip_vn_accents

LOCAL_EMBEDDING_MODEL_NAME = "local_ngram_v1_256d"
LOCAL_EMBEDDING_DIM = 256

VN_STOPWORDS = {
    "la", "cua", "va", "cac", "nhung", "co", "duoc", "cho", "toi", "minh", "ban",
    "theo", "ve", "trong", "khi", "nao", "nhu", "the", "khong", "can", "bao",
    "nhieu", "may", "gi", "ra", "sao", "mot", "voi", "tu", "den", "thi", "se",
    "da", "dang", "de", "tai", "hay", "hoac", "neu", "ma", "nay", "do", "bi",
    "ve", "bang", "qua", "len", "xuong", "o", "tren", "duoi", "cung", "het",
}

# Accented stopword forms so meaningful nouns like "thẻ" (card) or "từ" (in "thẻ từ") aren't erased by "thế"/"từ" collisions
VN_STOPWORDS_ACCENTED = {
    "là", "của", "và", "các", "những", "có", "được", "cho", "tôi", "mình", "bạn",
    "theo", "về", "trong", "khi", "nào", "như", "thế", "không", "cần", "bao",
    "nhiêu", "mấy", "gì", "ra", "sao", "một", "với", "đến", "thì", "sẽ",
    "đã", "đang", "để", "tại", "hay", "hoặc", "nếu", "mà", "này", "đó", "bị",
    "bằng", "quá", "lên", "xuống", "ở", "trên", "dưới", "cũng", "hết",
}

# Domain concept normalization (boosts Vietnamese semantic recall offline without distorting exact text)
HR_CONCEPT_ALIASES: List[Tuple[str, str]] = [
    (r"\b(?:di muon|tre gio|vao muon|cham gio)\b", "__concept_di_muon__"),
    (r"\b(?:an han|grace|qua bao nhieu phut|sau 08:35|5 phut)\b", "__concept_an_han_muon__"),
    (r"\b(?:thieu cham cong|quen cham cong|thieu gio vao|thieu gio ra|missing_punch)\b", "__concept_thieu_cham_cong__"),
    (r"\b(?:nghi phep|don nghi|don phep|xin nghi|phep nam|quy phep)\b", "__concept_nghi_phep__"),
    (r"\b(?:huy don|tu huy|huy phep)\b", "__concept_huy_don_phep__"),
    (r"\b(?:tang ca|lam them gio|overtime|\bot\b|cuoi tuan)\b", "__concept_tang_ca_ot__"),
    (r"\b(?:doi mat khau|thay doi mat khau|quen mat khau|bao mat tai khoan)\b", "__concept_doi_mat_khau__"),
    (r"\b(?:gio lam viec|nghi trua|08:30|17:30|ca lam viec|gio cong chuan)\b", "__concept_gio_lam_viec__"),
    (r"\b(?:phe duyet cap cao|ban dieu hanh|requires_executive_approval)\b", "__concept_phe_duyet_cap_cao__"),
    (r"\b(?:nghi trung|cung nghi|tap trung cap phong|25%|leave_cluster)\b", "__concept_r5_nghi_trung__"),
    (r"\b(?:vuot quy phep|leave_over_balance)\b", "__concept_r8_vuot_quy__"),
    (r"\b(?:giong het|trung giay|identical_punch)\b", "__concept_r6_trung_giay__"),
    (r"\b(?:ngay le|nghi le|tet duong|quoc khanh|30/04|01/05|02/09)\b", "__concept_ngay_le__"),
]


class EmbeddingProviderError(RuntimeError):
    """Raised when an external embedding provider fails or is misconfigured."""


@dataclass
class EmbeddingResolution:
    provider: "EmbeddingProvider"
    requested_provider: str
    offline_fallback: bool = False
    fallback_reason: Optional[str] = None


def tokenize_vietnamese_for_rag(text: str) -> List[str]:
    """Dual-channel Vietnamese tokenizer (accented + accent-folded + rule codes + domain concepts)."""
    lower = (text or "").lower()
    ascii_text = strip_vn_accents(lower)

    raw_accented = re.findall(r"[a-z0-9\u00c0-\u1ef9_:%/]+", lower)
    raw_ascii = re.findall(r"[a-z0-9_:%/]+", ascii_text)

    tokens: List[str] = []
    # Accent-folded unigrams (filtered by stopwords)
    clean_ascii = [t for t in raw_ascii if len(t) >= 2 and t not in VN_STOPWORDS]
    tokens.extend(clean_ascii)

    # Preserve accented forms when they differ (distinguishes Vietnamese words like "thức" vs "thực", "thẻ" vs "thế")
    clean_accented = [t for t in raw_accented if len(t) >= 2 and t not in VN_STOPWORDS_ACCENTED]
    for t in clean_accented:
        if t != strip_vn_accents(t):
            tokens.append(f"vn:{t}")

    # Accented bigrams (exact Vietnamese compound words: "công_thức" != "công_thực")
    for i in range(len(clean_accented) - 1):
        tokens.append(f"vbg:{clean_accented[i]}_{clean_accented[i + 1]}")

    # Accent-folded word bigrams (fallback for unaccented user typing)
    for i in range(len(clean_ascii) - 1):
        tokens.append(f"bg:{clean_ascii[i]}_{clean_ascii[i + 1]}")

    # Boost exact rule codes R1-R8
    for rc in re.findall(r"\br[1-8]\b", ascii_text):
        tokens.append(f"rule:{rc}")
        tokens.append(f"rule:{rc}")

    # Domain concept tags
    for pat, tag in HR_CONCEPT_ALIASES:
        if re.search(pat, ascii_text):
            tokens.append(tag)

    return tokens


def _stable_hash_bucket(feature: str, dim: int) -> Tuple[int, float]:
    """Process-deterministic signed feature hashing using blake2b (independent of PYTHONHASHSEED)."""
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    val = int.from_bytes(digest, "little", signed=False)
    bucket = val % dim
    sign = 1.0 if ((val >> 63) & 1) == 0 else -1.0
    return bucket, sign


class EmbeddingProvider(ABC):
    model_name: str
    dimension: int
    is_offline: bool

    @abstractmethod
    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        """Embed a batch of document chunk strings into dense float vectors."""

    def embed_query(self, text: str) -> List[float]:
        vecs = self.embed_texts([text])
        return vecs[0] if vecs else [0.0] * self.dimension


class LocalFeatureHashEmbeddingProvider(EmbeddingProvider):
    """Deterministic offline dense embedding engine (signed feature hashing over VN unigrams/bigrams/char n-grams + L2 norm).

    Produces real unit-normalized 256-d float vectors compatible with both SQLite cosine search and Supabase pgvector.
    Honestly reports model_name='local_ngram_v1_256d' (never pretends to be an external cloud model).
    """

    def __init__(self, dimension: int = LOCAL_EMBEDDING_DIM) -> None:
        self.dimension = dimension
        self.model_name = LOCAL_EMBEDDING_MODEL_NAME
        self.is_offline = True

    def _embed_single(self, text: str) -> List[float]:
        vec = np.zeros(self.dimension, dtype=np.float64)
        tokens = tokenize_vietnamese_for_rag(text)
        if not tokens:
            return [0.0] * self.dimension

        counts = Counter(tokens)
        for tok, tf in counts.items():
            sublinear_tf = 1.0 + math.log(tf)
            if tok.startswith("rule:") or tok.startswith("__concept_"):
                weight = 2.0 * sublinear_tf
            elif tok.startswith("bg:"):
                weight = 1.4 * sublinear_tf
            elif tok.startswith("vn:"):
                weight = 1.2 * sublinear_tf
            else:
                weight = 1.3 * sublinear_tf
            idx, sign = _stable_hash_bucket(tok, self.dimension)
            vec[idx] += sign * weight

        # Character 3- and 4-grams for Vietnamese morphological & typo resilience
        ascii_words = [
            w for w in re.findall(r"[a-z0-9]{3,}", strip_vn_accents((text or "").lower()))
            if w not in VN_STOPWORDS
        ]
        char_counts: Counter[str] = Counter()
        for w in ascii_words:
            padded = f"<{w}>"
            for n in (3, 4):
                for i in range(len(padded) - n + 1):
                    char_counts[f"cg{n}:{padded[i : i + n]}"] += 1
        for cg, tf in char_counts.items():
            idx, sign = _stable_hash_bucket(cg, self.dimension)
            vec[idx] += sign * 0.45 * (1.0 + math.log(tf))

        norm = float(np.linalg.norm(vec))
        if norm > 1e-12:
            vec = vec / norm
        return [round(float(x), 6) for x in vec.tolist()]

    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        return [self._embed_single(t) for t in texts]


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Real Google Gemini Embedding API provider via httpx (strictly fails honestly when API is unavailable)."""

    def __init__(
        self,
        api_key: str,
        model_name: str = "text-embedding-004",
        timeout_seconds: float = 12.0,
    ) -> None:
        if not api_key or not api_key.strip():
            raise EmbeddingProviderError("Thiếu LLM_API_KEY để gọi Gemini Embedding API.")
        self._api_key = api_key.strip()
        self.model_name = model_name.strip() or "text-embedding-004"
        self.dimension = 768
        self.is_offline = False
        self._timeout = timeout_seconds

    def _call_embed(self, text: str, task_type: str) -> List[float]:
        model_path = self.model_name if self.model_name.startswith("models/") else f"models/{self.model_name}"
        url = f"https://generativelanguage.googleapis.com/v1beta/{model_path}:embedContent"
        payload = {
            "model": model_path,
            "content": {"parts": [{"text": text[:8000]}]},
            "taskType": task_type,
        }
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(url, params={"key": self._api_key}, json=payload)
            if resp.status_code != 200:
                raise EmbeddingProviderError(f"Gemini Embedding API lỗi HTTP {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            values = data.get("embedding", {}).get("values")
            if not isinstance(values, list) or not values:
                raise EmbeddingProviderError("Gemini Embedding API trả về vector rỗng.")
            arr = np.asarray(values, dtype=np.float64)
            norm = float(np.linalg.norm(arr))
            if norm > 1e-12:
                arr = arr / norm
            self.dimension = int(arr.shape[0])
            return [round(float(x), 6) for x in arr.tolist()]
        except EmbeddingProviderError:
            raise
        except Exception as exc:
            raise EmbeddingProviderError(f"Không thể kết nối Gemini Embedding API: {exc}") from exc

    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        return [self._call_embed(t, "RETRIEVAL_DOCUMENT") for t in texts]

    def embed_query(self, text: str) -> List[float]:
        return self._call_embed(text, "RETRIEVAL_QUERY")


def read_embedding_settings(conn: Any) -> Dict[str, Any]:
    """Read embedding.provider, embedding.model_name, and embedding.chunk_size from system_settings safely."""
    out: Dict[str, Any] = {
        "provider": "local_bm25_hybrid",
        "model_name": LOCAL_EMBEDDING_MODEL_NAME,
        "chunk_size": 600,
    }
    try:
        rows = conn.execute(
            "SELECT setting_key, setting_value FROM system_settings WHERE setting_key IN ('embedding.provider', 'embedding.model_name', 'embedding.chunk_size')"
        ).fetchall()
        for r in rows:
            k = r["setting_key"]
            v = str(r["setting_value"]).strip()
            if k == "embedding.provider" and v:
                out["provider"] = v.lower()
            elif k == "embedding.model_name" and v:
                out["model_name"] = v
            elif k == "embedding.chunk_size" and v.isdigit():
                out["chunk_size"] = max(180, min(int(v), 2000))
    except Exception:
        if is_postgres_connection(conn):
            try:
                conn.rollback()
            except Exception:
                pass
    return out


def resolve_embedding_provider(
    conn: Any,
    allow_offline_fallback: bool = True,
    override_provider: Optional[str] = None,
) -> EmbeddingResolution:
    """Resolve active embedding provider honestly (never fakes cloud embedding when API key is missing)."""
    cfg = read_embedding_settings(conn)
    requested = (override_provider or cfg["provider"] or "local_bm25_hybrid").strip().lower()

    if requested == "gemini":
        api_key = (os.getenv("LLM_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
        if api_key:
            model = cfg["model_name"]
            if not model or "text-embedding-3" in model or model.startswith("local_"):
                model = "text-embedding-004"
            return EmbeddingResolution(
                provider=GeminiEmbeddingProvider(api_key=api_key, model_name=model),
                requested_provider="gemini",
                offline_fallback=False,
            )
        if not allow_offline_fallback:
            raise EmbeddingProviderError("embedding.provider=gemini nhưng chưa cấu hình LLM_API_KEY.")
        return EmbeddingResolution(
            provider=LocalFeatureHashEmbeddingProvider(),
            requested_provider="gemini",
            offline_fallback=True,
            fallback_reason="Chưa cấu hình LLM_API_KEY; chuyển sang Local Offline Embedding (local_ngram_v1_256d).",
        )

    return EmbeddingResolution(
        provider=LocalFeatureHashEmbeddingProvider(),
        requested_provider=requested,
        offline_fallback=False,
    )


def vector_to_pg_literal(vec: Sequence[float]) -> str:
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


def vector_to_json(vec: Sequence[float]) -> str:
    return json.dumps([round(float(x), 6) for x in vec], separators=(",", ":"))


def json_to_vector(raw: Any) -> Optional[np.ndarray]:
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        return np.asarray(raw, dtype=np.float64)
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list) and parsed:
                return np.asarray(parsed, dtype=np.float64)
        except Exception:
            return None
    return None


def cosine_similarity(vec_a: Sequence[float] | np.ndarray, vec_b: Sequence[float] | np.ndarray) -> float:
    a = np.asarray(vec_a, dtype=np.float64)
    b = np.asarray(vec_b, dtype=np.float64)
    if a.shape != b.shape or a.size == 0:
        return 0.0
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na <= 1e-12 or nb <= 1e-12:
        return 0.0
    return float(np.dot(a, b) / (na * nb))
