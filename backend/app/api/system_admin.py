from __future__ import annotations

import datetime
import json
import sqlite3
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field

from app.core.permissions import ALL_PERMISSION_CODES, PROTECTED_ADMIN_PERMISSIONS
from app.core.security import (
    AuthenticatedUser,
    get_db_dependency,
    require_permissions,
    write_activity_log,
)
from app.db.connection import is_postgres_connection, is_postgres_url
from app.schemas.common import RoleEnum
from app.services.ai_rag_service import (
    archive_rag_document,
    ingest_rag_document,
    query_rag_knowledge,
    reindex_rag_document_real,
)
from app.services.rag_document_processor import RagDocumentProcessingError
from app.services.rag_embeddings import EmbeddingProviderError
from app.services.rag_retriever import _parse_json_meta

router = APIRouter(prefix="/api", tags=["system-admin-rbac"])

FORBIDDEN_CONFIG_SUBSTRINGS = ("secret", "password", "api_key", "apikey", "token", "private_key", "credential")


class RolePermissionsUpdateRequest(BaseModel):
    permissions: List[str] = Field(default_factory=list)


class SystemSettingUpdateItem(BaseModel):
    setting_key: str = Field(..., min_length=2, max_length=100)
    setting_value: str = Field(..., max_length=500)


class SystemConfigUpdateRequest(BaseModel):
    settings: List[SystemSettingUpdateItem] = Field(..., min_length=1)


class RagDocumentCreateRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    original_file_name: str = Field(..., min_length=2, max_length=200)
    document_type: str = Field(default="policy", max_length=60)
    version_label: Optional[str] = Field(default="v1.0", max_length=40)
    content: str = Field(..., min_length=10, max_length=200000)
    visibility: str = Field(default="all", max_length=30)
    effective_from: Optional[str] = Field(default=None, max_length=20)
    effective_to: Optional[str] = Field(default=None, max_length=20)
    supersedes_document_id: Optional[int] = Field(default=None)


class RagSearchRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=1000)
    mode: str = Field(default="hybrid", pattern="^(bm25|vector|hybrid)$")
    top_k: int = Field(default=5, ge=1, le=15)
    as_of_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    document_type: Optional[str] = Field(default=None, max_length=60)


class KioskDeviceCreateRequest(BaseModel):
    kiosk_device_id: str = Field(..., min_length=3, max_length=60)
    device_name: str = Field(..., min_length=2, max_length=120)
    location_name: Optional[str] = Field(default=None, max_length=120)
    branch_name: Optional[str] = Field(default=None, max_length=120)
    is_active: bool = True


class KioskDeviceUpdateRequest(BaseModel):
    device_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    location_name: Optional[str] = Field(default=None, max_length=120)
    branch_name: Optional[str] = Field(default=None, max_length=120)
    is_active: Optional[bool] = None


# =============================================================================
# 1. SYSTEM DASHBOARD (ADMIN TECHNICAL METRICS ONLY — NO HR BUSINESS PII)
# =============================================================================

@router.get("/admin/system-dashboard")
def get_system_dashboard(
    current_user: AuthenticatedUser = Depends(require_permissions("system.dashboard")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    role_rows = conn.execute(
        """
        SELECT e.role,
               COUNT(*) AS total_accounts,
               SUM(CASE WHEN u.is_active = 1 AND e.employment_status = 'active' THEN 1 ELSE 0 END) AS active_accounts,
               SUM(CASE WHEN u.is_active = 0 OR e.employment_status != 'active' THEN 1 ELSE 0 END) AS locked_accounts
        FROM users u
        JOIN employees e ON e.employee_id = u.employee_id
        GROUP BY e.role
        ORDER BY e.role
        """
    ).fetchall()

    accounts_by_role = {r["role"]: dict(r) for r in role_rows}
    total_accounts = sum(int(r["total_accounts"] or 0) for r in role_rows)
    active_accounts = sum(int(r["active_accounts"] or 0) for r in role_rows)
    locked_accounts = sum(int(r["locked_accounts"] or 0) for r in role_rows)

    roles_count = int(conn.execute("SELECT COUNT(*) FROM roles").fetchone()[0])
    permissions_count = int(conn.execute("SELECT COUNT(*) FROM permissions").fetchone()[0])
    activity_count = int(conn.execute("SELECT COUNT(*) FROM activity_logs").fetchone()[0])
    query_audit_count = int(conn.execute("SELECT COUNT(*) FROM query_audit_log").fetchone()[0])
    blocked_query_count = int(
        conn.execute("SELECT COUNT(*) FROM query_audit_log WHERE status = 'blocked'").fetchone()[0]
    )
    rag_docs_count = int(conn.execute("SELECT COUNT(*) FROM company_documents").fetchone()[0])
    rag_chunks_count = int(conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0])
    kiosk_total = int(conn.execute("SELECT COUNT(*) FROM kiosk_devices").fetchone()[0])
    if is_postgres_connection(conn):
        kiosk_active = int(
            conn.execute("SELECT COUNT(*) FROM kiosk_devices WHERE is_active = TRUE").fetchone()[0]
        )
    else:
        kiosk_active = int(
            conn.execute("SELECT COUNT(*) FROM kiosk_devices WHERE is_active = 1").fetchone()[0]
        )

    recent_events = [
        dict(r)
        for r in conn.execute(
            """
            SELECT al.id, al.actor_user_id, u.username AS actor_username,
                   al.action, al.entity_type, al.entity_id, al.created_at
            FROM activity_logs al
            LEFT JOIN users u ON u.user_id = al.actor_user_id
            ORDER BY al.id DESC
            LIMIT 10
            """
        ).fetchall()
    ]

    return {
        "scope": "system",
        "database_engine": "postgresql (supabase)" if is_postgres_url() else "sqlite",
        "health": "healthy",
        "kpis": {
            "total_accounts": total_accounts,
            "active_accounts": active_accounts,
            "locked_accounts": locked_accounts,
            "roles_count": roles_count,
            "permissions_count": permissions_count,
            "activity_logs_count": activity_count,
            "query_audit_count": query_audit_count,
            "blocked_query_count": blocked_query_count,
            "rag_documents_count": rag_docs_count,
            "rag_chunks_count": rag_chunks_count,
            "kiosk_devices_total": kiosk_total,
            "kiosk_devices_active": kiosk_active,
        },
        "accounts_by_role": [
            {
                "role": code,
                "total_accounts": int(accounts_by_role.get(code, {}).get("total_accounts", 0) or 0),
                "active_accounts": int(accounts_by_role.get(code, {}).get("active_accounts", 0) or 0),
                "locked_accounts": int(accounts_by_role.get(code, {}).get("locked_accounts", 0) or 0),
            }
            for code in ["employee", "manager", "hr", "executive", "admin"]
        ],
        "recent_security_events": recent_events,
    }


# =============================================================================
# 2. RBAC ROLES & PERMISSIONS MANAGEMENT (ADMIN ONLY)
# =============================================================================

@router.get("/rbac/roles")
def list_rbac_roles(
    current_user: AuthenticatedUser = Depends(require_permissions("role.manage")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    roles = conn.execute(
        "SELECT role_id, role_code, role_name, description, is_system_role FROM roles ORDER BY role_id ASC"
    ).fetchall()

    rp_rows = conn.execute(
        """
        SELECT r.role_code, p.permission_code
        FROM role_permissions rp
        JOIN roles r ON r.role_id = rp.role_id
        JOIN permissions p ON p.permission_id = rp.permission_id
        ORDER BY p.permission_code ASC
        """
    ).fetchall()
    perms_by_role: Dict[str, List[str]] = {}
    for row in rp_rows:
        perms_by_role.setdefault(row["role_code"], []).append(row["permission_code"])

    user_counts = {
        r["role"]: int(r["cnt"])
        for r in conn.execute(
            """
            SELECT e.role, COUNT(*) AS cnt
            FROM users u
            JOIN employees e ON e.employee_id = u.employee_id
            WHERE u.is_active = 1 AND e.employment_status = 'active'
            GROUP BY e.role
            """
        ).fetchall()
    }

    items = []
    for r in roles:
        code = r["role_code"]
        items.append(
            {
                "role_id": r["role_id"],
                "role_code": code,
                "role_name": r["role_name"],
                "description": r["description"],
                "is_system_role": bool(r["is_system_role"]),
                "active_users": user_counts.get(code, 0),
                "permissions": perms_by_role.get(code, []),
            }
        )
    return {"total": len(items), "items": items}


@router.get("/rbac/permissions")
def list_rbac_permissions(
    current_user: AuthenticatedUser = Depends(require_permissions("role.manage")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    rows = conn.execute(
        "SELECT permission_id, permission_code, permission_name, description FROM permissions ORDER BY permission_code ASC"
    ).fetchall()
    return {"total": len(rows), "items": [dict(r) for r in rows]}


@router.patch("/rbac/roles/{role_code}/permissions")
def update_role_permissions(
    role_code: str,
    payload: RolePermissionsUpdateRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("role.manage")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    role_row = conn.execute(
        "SELECT role_id, role_code, role_name FROM roles WHERE role_code = ?",
        (role_code,),
    ).fetchone()
    if not role_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy vai trò.")

    requested = sorted(set(payload.permissions))
    invalid = [p for p in requested if p not in ALL_PERMISSION_CODES]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Danh sách permission không hợp lệ: {', '.join(invalid)}",
        )

    # Guard: prevent Admin from locking themselves out of RBAC / Account management
    if role_code == RoleEnum.admin.value:
        missing_core = sorted(PROTECTED_ADMIN_PERMISSIONS - set(requested))
        if missing_core:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Không thể gỡ các quyền quản trị cốt lõi khỏi vai trò Admin: {', '.join(missing_core)}",
            )

    before_perms = [
        r["permission_code"]
        for r in conn.execute(
            """
            SELECT p.permission_code
            FROM role_permissions rp
            JOIN permissions p ON p.permission_id = rp.permission_id
            WHERE rp.role_id = ?
            ORDER BY p.permission_code
            """,
            (role_row["role_id"],),
        ).fetchall()
    ]

    perm_map = {
        r["permission_code"]: r["permission_id"]
        for r in conn.execute("SELECT permission_id, permission_code FROM permissions").fetchall()
    }

    conn.execute("DELETE FROM role_permissions WHERE role_id = ?", (role_row["role_id"],))
    for p_code in requested:
        pid = perm_map.get(p_code)
        if pid:
            conn.execute(
                "INSERT INTO role_permissions (role_id, permission_id) VALUES (?, ?)",
                (role_row["role_id"], pid),
            )

    write_activity_log(
        conn,
        actor_user_id=current_user.user_id,
        action="update_role_permissions",
        entity_type="role",
        entity_id=role_code,
        before_obj={"permissions": before_perms},
        after_obj={"permissions": requested},
    )
    conn.commit()
    return {"status": "ok", "role_code": role_code, "permissions": requested}


# =============================================================================
# 3. QUERY AUDIT LOGS (ADMIN ONLY — NO SECRETS/PASSWORDS)
# =============================================================================

@router.get("/audit/queries")
def list_query_audit_logs(
    role: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    query_type: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: AuthenticatedUser = Depends(require_permissions("audit.read")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    where_clauses = ["1 = 1"]
    params: List[Any] = []
    if role and role != "all":
        where_clauses.append("q.role = ?")
        params.append(role)
    if status_filter and status_filter != "all":
        where_clauses.append("q.status = ?")
        params.append(status_filter)
    if query_type and query_type != "all":
        where_clauses.append("q.query_type = ?")
        params.append(query_type)
    if search:
        like = f"%{search.strip()}%"
        where_clauses.append("(q.question LIKE ? OR COALESCE(q.tool_name, '') LIKE ? OR COALESCE(u.username, '') LIKE ?)")
        params.extend([like, like, like])

    rows = conn.execute(
        f"""
        SELECT q.id, q.asked_at, q.user_id, u.username, q.role,
               q.question AS query_text, q.query_type, q.tool_name, q.sql_text,
               q.scope, q.row_count AS result_count, q.success, q.status
        FROM query_audit_log q
        LEFT JOIN users u ON u.user_id = q.user_id
        WHERE {' AND '.join(where_clauses)}
        ORDER BY q.id DESC
        LIMIT ?
        """,
        [*params, limit],
    ).fetchall()

    items = []
    for r in rows:
        item = dict(r)
        item["success"] = bool(item.get("success", 1))
        items.append(item)
    return {"total": len(items), "items": items}


# =============================================================================
# 4. SYSTEM CONFIGURATION (ADMIN ONLY — NON-SECRET TECHNICAL SETTINGS)
# =============================================================================

@router.get("/system/config")
def get_system_config(
    category: Optional[str] = Query(default=None),
    current_user: AuthenticatedUser = Depends(require_permissions("system.manage")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    where = "WHERE category = ?" if (category and category != "all") else ""
    params: List[Any] = [category] if (category and category != "all") else []
    rows = conn.execute(
        f"""
        SELECT setting_key, category, setting_value, value_type, description, updated_by_user_id, updated_at
        FROM system_settings
        {where}
        ORDER BY category ASC, setting_key ASC
        """,
        params,
    ).fetchall()
    return {
        "total": len(rows),
        "database_engine": "postgresql (supabase)" if is_postgres_url() else "sqlite",
        "items": [dict(r) for r in rows],
    }


@router.patch("/system/config")
def update_system_config(
    payload: SystemConfigUpdateRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("system.manage")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    before_map: Dict[str, str] = {}
    after_map: Dict[str, str] = {}

    for item in payload.settings:
        key = item.setting_key.strip()
        key_lower = key.lower()
        if any(bad in key_lower for bad in FORBIDDEN_CONFIG_SUBSTRINGS):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Không được lưu secret/API key/password vào system_settings ({key}). Hãy quản lý bằng biến môi trường.",
            )
        existing = conn.execute(
            "SELECT setting_key, setting_value FROM system_settings WHERE setting_key = ?",
            (key,),
        ).fetchone()
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Không tìm thấy khóa cấu hình '{key}'.",
            )
        before_map[key] = existing["setting_value"]
        after_map[key] = item.setting_value.strip()
        conn.execute(
            """
            UPDATE system_settings
            SET setting_value = ?, updated_by_user_id = ?, updated_at = ?
            WHERE setting_key = ?
            """,
            (item.setting_value.strip(), current_user.user_id, now_str, key),
        )

    write_activity_log(
        conn,
        actor_user_id=current_user.user_id,
        action="update_system_config",
        entity_type="system_settings",
        entity_id=",".join(sorted(after_map.keys())),
        before_obj=before_map,
        after_obj=after_map,
    )
    conn.commit()
    return {"status": "ok", "updated": after_map}


# =============================================================================
# 5. RAG KNOWLEDGE DOCUMENTS MANAGEMENT (ADMIN & HR WITH rag.manage)
# =============================================================================

@router.get("/rag/documents")
def list_rag_documents(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    current_user: AuthenticatedUser = Depends(require_permissions("rag.manage")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    where_clause = "WHERE d.status = ?" if (status_filter and status_filter != "all") else ""
    params: List[Any] = [status_filter] if (status_filter and status_filter != "all") else []
    rows = conn.execute(
        f"""
        SELECT d.document_id, d.title, d.original_file_name, d.storage_bucket, d.storage_path,
               d.document_type, d.version_label, d.status, d.checksum_sha256, d.uploaded_by_user_id,
               u.username AS uploaded_by_username, d.uploaded_at, d.processed_at, d.metadata,
               COALESCE(d.visibility, 'all') AS visibility,
               d.effective_from, d.effective_to,
               COALESCE(d.is_current, 1) AS is_current,
               d.supersedes_document_id,
               (SELECT COUNT(*) FROM document_chunks c WHERE c.document_id = d.document_id) AS chunk_count
        FROM company_documents d
        LEFT JOIN users u ON u.user_id = d.uploaded_by_user_id
        {where_clause}
        ORDER BY d.document_id DESC
        """,
        params,
    ).fetchall()

    items: List[Dict[str, Any]] = []
    for r in rows:
        item = dict(r)
        meta = _parse_json_meta(item.get("metadata"))
        item["is_current"] = bool(item.get("is_current", 1))
        item["embedding_model"] = meta.get("embedding_model")
        item["embedding_dim"] = meta.get("embedding_dim")
        item["injection_flagged_chunks"] = int(meta.get("injection_flagged_chunks", 0) or 0)
        item["quarantined_chunks"] = int(meta.get("quarantined_chunks", 0) or 0)
        item["metadata"] = meta
        items.append(item)
    return {"total": len(items), "items": items}


@router.post("/rag/documents", status_code=status.HTTP_201_CREATED)
def create_rag_document(
    payload: RagDocumentCreateRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("rag.manage")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    try:
        return ingest_rag_document(
            conn=conn,
            actor_user_id=current_user.user_id,
            title=payload.title,
            original_file_name=payload.original_file_name,
            document_type=payload.document_type,
            version_label=payload.version_label,
            content=payload.content,
            visibility=payload.visibility,
            effective_from=payload.effective_from,
            effective_to=payload.effective_to,
            supersedes_document_id=payload.supersedes_document_id,
        )
    except RagDocumentProcessingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except EmbeddingProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.post("/rag/documents/upload", status_code=status.HTTP_201_CREATED)
async def upload_rag_document_file(
    file: UploadFile = File(...),
    title: str = Form(...),
    document_type: str = Form(default="policy"),
    version_label: str = Form(default="v1.0"),
    visibility: str = Form(default="all"),
    effective_from: Optional[str] = Form(default=None),
    effective_to: Optional[str] = Form(default=None),
    supersedes_document_id: Optional[int] = Form(default=None),
    current_user: AuthenticatedUser = Depends(require_permissions("rag.manage")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    """Upload and index a PDF, DOCX, TXT, or MD file into company_documents + document_chunks."""
    raw_bytes = await file.read()
    try:
        return ingest_rag_document(
            conn=conn,
            actor_user_id=current_user.user_id,
            title=title,
            original_file_name=file.filename or "document.txt",
            document_type=document_type,
            version_label=version_label,
            raw_bytes=raw_bytes,
            visibility=visibility,
            effective_from=effective_from,
            effective_to=effective_to,
            supersedes_document_id=supersedes_document_id,
        )
    except RagDocumentProcessingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except EmbeddingProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.get("/rag/documents/{doc_id}/chunks")
def list_rag_document_chunks(
    doc_id: int,
    current_user: AuthenticatedUser = Depends(require_permissions("rag.manage")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    doc = conn.execute(
        "SELECT document_id, title, version_label, status, visibility FROM company_documents WHERE document_id = ?",
        (doc_id,),
    ).fetchone()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy tài liệu RAG.")

    pg = is_postgres_connection(conn)
    has_vec_expr = "(embedding IS NOT NULL)" if pg else "(embedding_json IS NOT NULL)"
    rows = conn.execute(
        f"""
        SELECT chunk_id, document_id, chunk_index, content, embedding_model, embedding_dim,
               {has_vec_expr} AS has_embedding, metadata, created_at
        FROM document_chunks
        WHERE document_id = ?
        ORDER BY chunk_index ASC
        """,
        (doc_id,),
    ).fetchall()
    items = []
    for r in rows:
        item = dict(r)
        item["has_embedding"] = bool(item.get("has_embedding"))
        item["metadata"] = _parse_json_meta(item.get("metadata"))
        items.append(item)
    return {"document": dict(doc), "total": len(items), "items": items}


@router.post("/rag/documents/{doc_id}/reindex")
def reindex_rag_document(
    doc_id: int,
    current_user: AuthenticatedUser = Depends(require_permissions("rag.manage")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    try:
        return reindex_rag_document_real(conn=conn, doc_id=doc_id, actor_user_id=current_user.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except RagDocumentProcessingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except EmbeddingProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.post("/rag/documents/{doc_id}/archive")
def archive_rag_document_endpoint(
    doc_id: int,
    current_user: AuthenticatedUser = Depends(require_permissions("rag.manage")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    try:
        return archive_rag_document(conn=conn, doc_id=doc_id, actor_user_id=current_user.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.delete("/rag/documents/{doc_id}")
def delete_rag_document(
    doc_id: int,
    current_user: AuthenticatedUser = Depends(require_permissions("rag.manage")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    doc = conn.execute("SELECT document_id, title, original_file_name FROM company_documents WHERE document_id = ?", (doc_id,)).fetchone()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy tài liệu RAG.")
    conn.execute("DELETE FROM company_documents WHERE document_id = ?", (doc_id,))
    write_activity_log(
        conn,
        actor_user_id=current_user.user_id,
        action="delete_rag_document",
        entity_type="company_document",
        entity_id=str(doc_id),
        before_obj=dict(doc),
    )
    conn.commit()
    return {"status": "ok", "deleted_document_id": doc_id}


@router.post("/rag/search")
def search_rag_knowledge_endpoint(
    payload: RagSearchRequest,
    current_user: AuthenticatedUser = Depends(
        require_permissions("ai.ask.self", "ai.ask.department", "ai.ask.all", "ai.strategy")
    ),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    """RBAC-scoped RAG retrieval endpoint (BM25 / Vector / Hybrid + Citations + Injection Defense)."""
    return query_rag_knowledge(
        conn=conn,
        user=current_user,
        question=payload.question,
        mode=payload.mode,
        top_k=payload.top_k,
        as_of_date=payload.as_of_date,
        document_type=payload.document_type,
    )


# =============================================================================
# 6. FACE KIOSK DEVICES MANAGEMENT (ADMIN ONLY)
# =============================================================================

@router.get("/kiosk/devices")
def list_kiosk_devices(
    current_user: AuthenticatedUser = Depends(require_permissions("kiosk.manage")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    rows = conn.execute(
        """
        SELECT kiosk_device_id, device_name, location_name, branch_name,
               assigned_user_id, is_active, last_seen_at, created_at, updated_at
        FROM kiosk_devices
        ORDER BY kiosk_device_id ASC
        """
    ).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        d["is_active"] = bool(d["is_active"])
        items.append(d)
    return {"total": len(items), "items": items}


@router.post("/kiosk/devices", status_code=status.HTTP_201_CREATED)
def create_kiosk_device(
    payload: KioskDeviceCreateRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("kiosk.manage")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    dev_id = payload.kiosk_device_id.strip().upper()
    if conn.execute("SELECT 1 FROM kiosk_devices WHERE kiosk_device_id = ?", (dev_id,)).fetchone():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Thiết bị {dev_id} đã tồn tại.")

    active_val: Any = bool(payload.is_active) if is_postgres_connection(conn) else (1 if payload.is_active else 0)
    conn.execute(
        """
        INSERT INTO kiosk_devices (kiosk_device_id, device_name, location_name, branch_name, is_active)
        VALUES (?, ?, ?, ?, ?)
        """,
        (dev_id, payload.device_name.strip(), payload.location_name, payload.branch_name, active_val),
    )
    write_activity_log(
        conn,
        actor_user_id=current_user.user_id,
        action="manage_kiosk_device",
        entity_type="kiosk_device",
        entity_id=dev_id,
        after_obj=payload.model_dump(mode="json"),
    )
    conn.commit()
    return {"status": "ok", "kiosk_device_id": dev_id}


@router.patch("/kiosk/devices/{device_id}")
def update_kiosk_device(
    device_id: str,
    payload: KioskDeviceUpdateRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("kiosk.manage")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    existing = conn.execute(
        "SELECT kiosk_device_id, device_name, location_name, branch_name, is_active FROM kiosk_devices WHERE kiosk_device_id = ?",
        (device_id,),
    ).fetchone()
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy thiết bị Kiosk.")

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return {"status": "ok", "kiosk_device_id": device_id}

    if "is_active" in updates:
        updates["is_active"] = bool(updates["is_active"]) if is_postgres_connection(conn) else (1 if updates["is_active"] else 0)
    updates["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    set_clauses = [f"{col} = ?" for col in updates.keys()]
    conn.execute(
        f"UPDATE kiosk_devices SET {', '.join(set_clauses)} WHERE kiosk_device_id = ?",
        [*updates.values(), device_id],
    )
    write_activity_log(
        conn,
        actor_user_id=current_user.user_id,
        action="manage_kiosk_device",
        entity_type="kiosk_device",
        entity_id=device_id,
        before_obj=dict(existing),
        after_obj=payload.model_dump(exclude_unset=True, mode="json"),
    )
    conn.commit()
    return {"status": "ok", "kiosk_device_id": device_id}
