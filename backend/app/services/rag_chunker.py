from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.rag_security import scan_text_for_prompt_injection

DEFAULT_CHUNK_SIZE = 600
DEFAULT_CHUNK_OVERLAP = 100
MIN_CHUNK_SIZE = 180
MAX_CHUNK_SIZE = 2000

PAGE_MARKER_RE = re.compile(r"^\[Trang\s+(\d+)\]$", flags=re.IGNORECASE)
MD_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$")
VN_ARTICLE_RE = re.compile(
    r"^((?:Chương|Mục|Phần|Điều|Khoản|Quy\s*tắc)\s+[0-9IVXivxR]+(?:\.[0-9]+)?)\s*[\.:\-–—]?\s*(.*)$",
    flags=re.IGNORECASE,
)


@dataclass
class StructuredChunk:
    chunk_index: int
    content: str
    section_title: str
    article_ref: Optional[str]
    page_number: Optional[int]
    char_start: int
    char_end: int
    metadata: Dict[str, Any] = field(default_factory=dict)


def _split_long_text_with_overlap(text: str, max_len: int, overlap: int) -> List[str]:
    """Split an oversized block along sentence/line boundaries while preserving overlap."""
    clean = text.strip()
    if len(clean) <= max_len:
        return [clean] if clean else []

    # Split into sentences or lines first
    units = [u.strip() for u in re.split(r"(?<=[.!?;:])\s+|\n+", clean) if u.strip()]
    if not units:
        units = [clean]

    pieces: List[str] = []
    buf = ""
    for unit in units:
        if len(unit) > max_len:
            if buf:
                pieces.append(buf)
                buf = ""
            # Hard window split with overlap for single run-on sentence
            step = max(50, max_len - overlap)
            pos = 0
            while pos < len(unit):
                seg = unit[pos : pos + max_len].strip()
                if seg:
                    pieces.append(seg)
                if pos + max_len >= len(unit):
                    break
                pos += step
            continue

        candidate = f"{buf} {unit}".strip() if buf else unit
        if len(candidate) <= max_len:
            buf = candidate
        else:
            if buf:
                pieces.append(buf)
                tail = buf[-overlap:].strip() if overlap > 0 and len(buf) > overlap else ""
                # Avoid cutting mid-word in overlap tail
                if tail and " " in tail:
                    tail = tail.split(" ", 1)[1].strip()
                buf = f"{tail} {unit}".strip() if tail and len(tail) + len(unit) + 1 <= max_len else unit
            else:
                buf = unit
    if buf:
        pieces.append(buf)
    return pieces


def chunk_document_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    doc_meta: Optional[Dict[str, Any]] = None,
) -> List[StructuredChunk]:
    """Split a normalized document into structured section/article/page-aware chunks with injection scan."""
    eff_size = max(MIN_CHUNK_SIZE, min(int(chunk_size or DEFAULT_CHUNK_SIZE), MAX_CHUNK_SIZE))
    eff_overlap = max(0, min(int(chunk_overlap or 0), eff_size // 3))

    clean_text = (text or "").strip()
    if not clean_text:
        return []

    # Step 1: Parse document into structural sections tracking heading, article_ref, and page_number
    sections: List[Dict[str, Any]] = []
    cur_section_title = (doc_meta or {}).get("title") or "Tổng quan"
    cur_article_ref: Optional[str] = None
    cur_page: Optional[int] = None
    cur_lines: List[str] = []

    def _flush_section() -> None:
        nonlocal cur_lines
        body = "\n".join(cur_lines).strip()
        if body:
            sections.append(
                {
                    "section_title": cur_section_title,
                    "article_ref": cur_article_ref,
                    "page_number": cur_page,
                    "body": body,
                }
            )
        cur_lines = []

    for raw_line in clean_text.split("\n"):
        line = raw_line.strip()
        if not line:
            if cur_lines and cur_lines[-1] != "":
                cur_lines.append("")
            continue

        page_m = PAGE_MARKER_RE.match(line)
        if page_m:
            _flush_section()
            cur_page = int(page_m.group(1))
            continue

        md_m = MD_HEADING_RE.match(line)
        if md_m:
            _flush_section()
            heading_txt = md_m.group(2).strip()
            cur_section_title = heading_txt
            art_m = VN_ARTICLE_RE.match(heading_txt)
            cur_article_ref = art_m.group(1).strip() if art_m else None
            cur_lines.append(heading_txt)
            continue

        art_m = VN_ARTICLE_RE.match(line)
        if art_m and len(line) <= 180:
            _flush_section()
            cur_article_ref = art_m.group(1).strip()
            cur_section_title = line
            cur_lines.append(line)
            continue

        cur_lines.append(line)

    _flush_section()

    # Step 2: Pack paragraphs within each section respecting chunk_size + chunk_overlap
    chunks: List[StructuredChunk] = []
    cursor_offset = 0

    for sec in sections:
        sec_title = sec["section_title"]
        art_ref = sec["article_ref"]
        page_num = sec["page_number"]
        paragraphs = [p.strip() for p in sec["body"].split("\n\n") if p.strip()]

        sec_chunks_text: List[str] = []
        buf = ""
        for para in paragraphs:
            if len(para) > eff_size:
                if buf:
                    sec_chunks_text.append(buf)
                    buf = ""
                sec_chunks_text.extend(_split_long_text_with_overlap(para, eff_size, eff_overlap))
                continue

            if buf and len(buf) + len(para) + 2 > eff_size:
                sec_chunks_text.append(buf)
                tail = buf[-eff_overlap:].strip() if eff_overlap > 0 and len(buf) > eff_overlap else ""
                if tail and " " in tail:
                    tail = tail.split(" ", 1)[1].strip()
                if tail and len(tail) + len(para) + 2 <= eff_size:
                    buf = f"{tail}\n{para}"
                else:
                    buf = para
            else:
                buf = f"{buf}\n\n{para}" if buf else para
        if buf:
            sec_chunks_text.append(buf)

        for chunk_txt in sec_chunks_text:
            # Ensure section title context is preserved for standalone retrieval if not already at start
            final_txt = chunk_txt
            if sec_title and not chunk_txt.lower().startswith(sec_title.lower()[:24]):
                prefixed = f"[{sec_title}]\n{chunk_txt}"
                if len(prefixed) <= eff_size + 160:
                    final_txt = prefixed

            start_pos = clean_text.find(chunk_txt[:40], cursor_offset)
            if start_pos < 0:
                start_pos = cursor_offset
            end_pos = start_pos + len(chunk_txt)
            cursor_offset = max(cursor_offset, start_pos)

            inj = scan_text_for_prompt_injection(final_txt)
            idx = len(chunks)
            meta: Dict[str, Any] = {
                "chunk_index": idx,
                "section_title": sec_title,
                "article_ref": art_ref,
                "page_number": page_num,
                "char_start": start_pos,
                "char_end": end_pos,
                "length": len(final_txt),
                "word_count": len(final_txt.split()),
                "injection_flagged": inj["flagged"],
                "injection_risk_score": inj["risk_score"],
                "injection_patterns": inj["matched_patterns"],
                "quarantined": inj["quarantined"],
            }
            if doc_meta:
                for k in ("version_label", "document_type", "visibility", "effective_from", "effective_to"):
                    if k in doc_meta and doc_meta[k] is not None:
                        meta[k] = doc_meta[k]

            chunks.append(
                StructuredChunk(
                    chunk_index=idx,
                    content=final_txt,
                    section_title=sec_title,
                    article_ref=art_ref,
                    page_number=page_num,
                    char_start=start_pos,
                    char_end=end_pos,
                    metadata=meta,
                )
            )

    return chunks
