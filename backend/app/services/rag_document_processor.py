from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import docx
from pypdf import PdfReader

ALLOWED_RAG_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
MAX_RAG_FILE_BYTES = 10 * 1024 * 1024  # 10 MB safety limit
MIN_EXTRACTED_CHARS = 10


class RagDocumentProcessingError(ValueError):
    """Raised when an uploaded RAG document fails validation or text extraction."""


@dataclass
class ExtractedDocument:
    original_file_name: str
    file_extension: str
    text: str
    checksum_sha256: str
    byte_size: int
    page_count: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)


def sanitize_file_name(file_name: str) -> str:
    base = Path((file_name or "").replace("\\", "/")).name.strip()
    if not base or base in (".", ".."):
        raise RagDocumentProcessingError("Tên tệp tài liệu không hợp lệ.")
    cleaned = re.sub(r"[^a-zA-Z0-9._\-\u00C0-\u1EF9 ]+", "_", base)
    return cleaned[:200]


def normalize_extracted_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Remove invisible zero-width / control chars except tab and newline
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b\ufeff]", "", text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    normalized = "\n".join(lines)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    return normalized


def _extract_pdf(raw_bytes: bytes) -> tuple[str, int, Dict[str, Any]]:
    if not raw_bytes.startswith(b"%PDF-"):
        raise RagDocumentProcessingError("Tệp PDF không hợp lệ (sai chữ ký định dạng %PDF-).")
    try:
        reader = PdfReader(io.BytesIO(raw_bytes))
    except Exception as exc:
        raise RagDocumentProcessingError(f"Không thể mở tệp PDF (tệp lỗi hoặc bị hỏng): {exc}") from exc

    if reader.is_encrypted:
        raise RagDocumentProcessingError("Tệp PDF đang được bảo vệ bằng mật khẩu, không thể trích xuất nội dung.")

    pages_out: List[str] = []
    non_empty_pages = 0
    for idx, page in enumerate(reader.pages, start=1):
        try:
            page_txt = page.extract_text() or ""
        except Exception as exc:
            raise RagDocumentProcessingError(f"Lỗi trích xuất văn bản tại trang {idx} của PDF: {exc}") from exc
        cleaned = normalize_extracted_text(page_txt)
        if cleaned:
            non_empty_pages += 1
            pages_out.append(f"[Trang {idx}]\n{cleaned}")

    full_text = "\n\n".join(pages_out).strip()
    if len(full_text) < MIN_EXTRACTED_CHARS:
        raise RagDocumentProcessingError(
            "Không trích xuất được nội dung văn bản từ PDF (có thể là PDF scan dạng ảnh chưa qua OCR)."
        )
    return full_text, len(reader.pages), {"non_empty_pages": non_empty_pages, "parser": "pypdf"}


def _extract_docx(raw_bytes: bytes) -> tuple[str, int, Dict[str, Any]]:
    if not raw_bytes.startswith(b"PK\x03\x04"):
        raise RagDocumentProcessingError("Tệp DOCX không hợp lệ (không phải gói OOXML/ZIP chuẩn).")
    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes), "r") as zf:
            names = set(zf.namelist())
            if "word/document.xml" not in names:
                raise RagDocumentProcessingError("Tệp DOCX thiếu cấu trúc word/document.xml hợp lệ.")
    except RagDocumentProcessingError:
        raise
    except Exception as exc:
        raise RagDocumentProcessingError(f"Tệp DOCX bị lỗi cấu trúc nén: {exc}") from exc

    try:
        doc = docx.Document(io.BytesIO(raw_bytes))
    except Exception as exc:
        raise RagDocumentProcessingError(f"Không thể đọc nội dung tệp DOCX: {exc}") from exc

    blocks: List[str] = []
    heading_count = 0
    for para in doc.paragraphs:
        txt = (para.text or "").strip()
        if not txt:
            continue
        style_name = (para.style.name if para.style else "") or ""
        style_lower = style_name.lower()
        if style_lower.startswith("heading 1") or style_lower == "title":
            blocks.append(f"# {txt}")
            heading_count += 1
        elif style_lower.startswith("heading 2"):
            blocks.append(f"## {txt}")
            heading_count += 1
        elif style_lower.startswith("heading 3"):
            blocks.append(f"### {txt}")
            heading_count += 1
        else:
            blocks.append(txt)

    table_rows_extracted = 0
    for table in doc.tables:
        t_lines: List[str] = []
        for row in table.rows:
            cells = [re.sub(r"\s+", " ", (c.text or "").strip()) for c in row.cells]
            if any(cells):
                t_lines.append(" | ".join(cells))
                table_rows_extracted += 1
        if t_lines:
            blocks.append("\n".join(t_lines))

    full_text = normalize_extracted_text("\n\n".join(blocks))
    if len(full_text) < MIN_EXTRACTED_CHARS:
        raise RagDocumentProcessingError("Tệp DOCX không có đủ nội dung văn bản để đánh chỉ mục.")
    return full_text, 1, {
        "heading_count": heading_count,
        "table_rows_extracted": table_rows_extracted,
        "parser": "python-docx",
    }


def _extract_plain_text(raw_bytes: bytes, ext: str) -> tuple[str, int, Dict[str, Any]]:
    if b"\x00" in raw_bytes[:4096]:
        raise RagDocumentProcessingError(f"Tệp {ext} chứa dữ liệu nhị phân không hợp lệ.")

    decoded = None
    used_encoding = "utf-8"
    for enc in ("utf-8-sig", "utf-8", "cp1258", "cp1252"):
        try:
            decoded = raw_bytes.decode(enc)
            used_encoding = enc
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise RagDocumentProcessingError(f"Không thể giải mã bảng mã ký tự của tệp {ext}.")

    full_text = normalize_extracted_text(decoded)
    if len(full_text) < MIN_EXTRACTED_CHARS:
        raise RagDocumentProcessingError("Nội dung tệp văn bản quá ngắn (tối thiểu 10 ký tự).")
    return full_text, 1, {"encoding": used_encoding, "parser": "text"}


def validate_and_extract_file(file_name: str, raw_bytes: bytes) -> ExtractedDocument:
    """Validate file extension, size, magic signature, and extract clean text from PDF/DOCX/TXT/MD."""
    safe_name = sanitize_file_name(file_name)
    ext = Path(safe_name).suffix.lower()
    if ext not in ALLOWED_RAG_EXTENSIONS:
        raise RagDocumentProcessingError(
            f"Định dạng '{ext or 'không xác định'}' không được hỗ trợ. Chỉ chấp nhận: PDF, DOCX, TXT, MD."
        )
    if not raw_bytes:
        raise RagDocumentProcessingError("Tệp tải lên rỗng (0 bytes).")
    if len(raw_bytes) > MAX_RAG_FILE_BYTES:
        raise RagDocumentProcessingError(
            f"Kích thước tệp ({len(raw_bytes) / (1024 * 1024):.1f} MB) vượt quá giới hạn 10 MB."
        )

    checksum = hashlib.sha256(raw_bytes).hexdigest()
    if ext == ".pdf":
        text, page_count, meta = _extract_pdf(raw_bytes)
    elif ext == ".docx":
        text, page_count, meta = _extract_docx(raw_bytes)
    else:
        text, page_count, meta = _extract_plain_text(raw_bytes, ext)

    return ExtractedDocument(
        original_file_name=safe_name,
        file_extension=ext,
        text=text,
        checksum_sha256=checksum,
        byte_size=len(raw_bytes),
        page_count=page_count,
        metadata={
            **meta,
            "byte_size": len(raw_bytes),
            "page_count": page_count,
            "char_count": len(text),
        },
    )


def prepare_raw_text_document(file_name: str, content: str) -> ExtractedDocument:
    """Validate and normalize direct Markdown/text content submitted via JSON API."""
    safe_name = sanitize_file_name(file_name or "document.md")
    ext = Path(safe_name).suffix.lower() or ".md"
    if ext not in {".txt", ".md"}:
        ext = ".md"
    raw_bytes = (content or "").encode("utf-8")
    if len(raw_bytes) > MAX_RAG_FILE_BYTES:
        raise RagDocumentProcessingError("Nội dung văn bản vượt quá giới hạn 10 MB.")
    normalized = normalize_extracted_text(content or "")
    if len(normalized) < MIN_EXTRACTED_CHARS:
        raise RagDocumentProcessingError("Nội dung tài liệu quá ngắn (tối thiểu 10 ký tự).")
    return ExtractedDocument(
        original_file_name=safe_name,
        file_extension=ext,
        text=normalized,
        checksum_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        byte_size=len(raw_bytes),
        page_count=1,
        metadata={"parser": "raw_text", "byte_size": len(raw_bytes), "page_count": 1, "char_count": len(normalized)},
    )
