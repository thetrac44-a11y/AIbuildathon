from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import bcrypt

from app.core.permissions import (
    DEFAULT_KIOSK_DEVICES,
    DEFAULT_RAG_DOCUMENTS,
    DEFAULT_ROLE_PERMISSIONS,
    DEFAULT_SYSTEM_SETTINGS,
    PERMISSION_CATALOG,
    ROLE_CATALOG,
)
from app.db.connection import get_connection, is_postgres_connection

DEV_DEFAULT_PASSWORD = os.getenv("DEV_SEED_PASSWORD", "Demo@123")


def _sqlite_table_exists(conn: Any, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _sqlite_column_names(conn: Any, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {r["name"] for r in rows}


def _sqlite_table_sql(conn: Any, table_name: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return str(row["sql"] or "") if row else ""


def _ensure_sqlite_rbac_schema(conn: Any) -> Dict[str, Any]:
    """Non-destructively upgrade an existing SQLite database to 5-role RBAC + extended audit/admin tables."""
    changes: List[str] = []

    # 0. Crash-recovery guard: if a previous interrupted migration left legacy staging tables, restore rows safely
    if _sqlite_table_exists(conn, "_employees_legacy_3role"):
        conn.execute("PRAGMA foreign_keys = OFF;")
        conn.execute("PRAGMA legacy_alter_table = ON;")
        cur_cnt = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        if cur_cnt == 0:
            conn.execute(
                """
                INSERT OR IGNORE INTO employees (
                    employee_id, full_name, department_id, position, manager_id,
                    start_date, annual_leave_balance, role, employment_status, email, phone
                )
                SELECT
                    employee_id, full_name, department_id, position, manager_id,
                    start_date, annual_leave_balance, role, employment_status, email, phone
                FROM _employees_legacy_3role
                """
            )
        conn.execute("DROP TABLE _employees_legacy_3role;")
        conn.execute("PRAGMA legacy_alter_table = OFF;")
        conn.execute("PRAGMA foreign_keys = ON;")
        changes.append("recovered rows safely from _employees_legacy_3role")

    if _sqlite_table_exists(conn, "_query_audit_log_legacy"):
        conn.execute("PRAGMA foreign_keys = OFF;")
        conn.execute("PRAGMA legacy_alter_table = ON;")
        qa_cols = _sqlite_column_names(conn, "_query_audit_log_legacy")
        cur_qa = conn.execute("SELECT COUNT(*) FROM query_audit_log").fetchone()[0]
        if cur_qa == 0:
            qt_expr = "query_type" if "query_type" in qa_cols else "'ai_sql'"
            sc_expr = "scope" if "scope" in qa_cols else "CASE WHEN role IN ('hr', 'executive') THEN 'all' WHEN role = 'manager' THEN 'department' WHEN role = 'admin' THEN 'system' ELSE 'self' END"
            ok_expr = "success" if "success" in qa_cols else "CASE WHEN status = 'success' THEN 1 ELSE 0 END"
            conn.execute(
                f"""
                INSERT OR IGNORE INTO query_audit_log (
                    id, asked_at, user_id, role, question, query_type, tool_name, sql_text, scope, row_count, success, status
                )
                SELECT
                    id, asked_at, user_id, role, question, {qt_expr}, tool_name, sql_text, {sc_expr}, row_count, {ok_expr}, status
                FROM _query_audit_log_legacy
                """
            )
        conn.execute("DROP TABLE _query_audit_log_legacy;")
        conn.execute("PRAGMA legacy_alter_table = OFF;")
        conn.execute("PRAGMA foreign_keys = ON;")
        changes.append("recovered rows safely from _query_audit_log_legacy")

    # 1. Upgrade employees table CHECK constraint if it still only has 3 roles
    if _sqlite_table_exists(conn, "employees"):
        emp_sql = _sqlite_table_sql(conn, "employees")
        if "'executive'" not in emp_sql or "'admin'" not in emp_sql:
            conn.execute("PRAGMA foreign_keys = OFF;")
            conn.execute("PRAGMA legacy_alter_table = ON;")
            conn.execute("ALTER TABLE employees RENAME TO _employees_legacy_3role;")
            conn.execute(
                """
                CREATE TABLE employees (
                    employee_id TEXT PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    department_id TEXT NOT NULL,
                    position TEXT NOT NULL,
                    manager_id TEXT NULL,
                    start_date TEXT NOT NULL,
                    annual_leave_balance REAL NOT NULL DEFAULT 12.0 CHECK (annual_leave_balance >= 0),
                    role TEXT NOT NULL CHECK (role IN ('employee', 'manager', 'hr', 'executive', 'admin')),
                    employment_status TEXT NOT NULL DEFAULT 'active' CHECK (employment_status IN ('active', 'inactive', 'terminated')),
                    email TEXT UNIQUE,
                    phone TEXT NULL,
                    FOREIGN KEY (department_id) REFERENCES departments(department_id) ON UPDATE CASCADE ON DELETE RESTRICT,
                    FOREIGN KEY (manager_id) REFERENCES employees(employee_id) ON UPDATE CASCADE ON DELETE SET NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO employees (
                    employee_id, full_name, department_id, position, manager_id,
                    start_date, annual_leave_balance, role, employment_status, email, phone
                )
                SELECT
                    employee_id, full_name, department_id, position, manager_id,
                    start_date, annual_leave_balance, role, employment_status, email, phone
                FROM _employees_legacy_3role
                """
            )
            conn.execute("DROP TABLE _employees_legacy_3role;")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_employees_dept ON employees(department_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_employees_role ON employees(role);")
            conn.execute("PRAGMA legacy_alter_table = OFF;")
            conn.execute("PRAGMA foreign_keys = ON;")
            changes.append("upgraded employees.role CHECK constraint to 5 roles (preserving all rows)")

    # 2. Upgrade query_audit_log CHECK constraint and add query_type, scope, success columns
    if _sqlite_table_exists(conn, "query_audit_log"):
        qa_sql = _sqlite_table_sql(conn, "query_audit_log")
        qa_cols = _sqlite_column_names(conn, "query_audit_log")
        if "'executive'" not in qa_sql or "'admin'" not in qa_sql:
            conn.execute("PRAGMA foreign_keys = OFF;")
            conn.execute("PRAGMA legacy_alter_table = ON;")
            conn.execute("ALTER TABLE query_audit_log RENAME TO _query_audit_log_legacy;")
            conn.execute(
                """
                CREATE TABLE query_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asked_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('employee', 'manager', 'hr', 'executive', 'admin')),
                    question TEXT NOT NULL,
                    query_type TEXT NOT NULL DEFAULT 'ai_sql',
                    tool_name TEXT NULL,
                    sql_text TEXT NULL,
                    scope TEXT NOT NULL DEFAULT 'self',
                    row_count INTEGER NOT NULL DEFAULT 0,
                    success INTEGER NOT NULL DEFAULT 1 CHECK (success IN (0, 1)),
                    status TEXT NOT NULL CHECK (status IN ('success', 'blocked', 'error', 'insufficient_data'))
                )
                """
            )
            qt_expr = "query_type" if "query_type" in qa_cols else "'ai_sql'"
            sc_expr = "scope" if "scope" in qa_cols else "CASE WHEN role IN ('hr', 'executive') THEN 'all' WHEN role = 'manager' THEN 'department' WHEN role = 'admin' THEN 'system' ELSE 'self' END"
            ok_expr = "success" if "success" in qa_cols else "CASE WHEN status = 'success' THEN 1 ELSE 0 END"
            conn.execute(
                f"""
                INSERT INTO query_audit_log (
                    id, asked_at, user_id, role, question, query_type, tool_name, sql_text, scope, row_count, success, status
                )
                SELECT
                    id, asked_at, user_id, role, question, {qt_expr}, tool_name, sql_text, {sc_expr}, row_count, {ok_expr}, status
                FROM _query_audit_log_legacy
                """
            )
            conn.execute("DROP TABLE _query_audit_log_legacy;")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_query_audit_asked ON query_audit_log(asked_at);")
            conn.execute("PRAGMA legacy_alter_table = OFF;")
            conn.execute("PRAGMA foreign_keys = ON;")
            changes.append("upgraded query_audit_log CHECK + columns (preserving all rows)")
        else:
            if "query_type" not in qa_cols:
                conn.execute("ALTER TABLE query_audit_log ADD COLUMN query_type TEXT NOT NULL DEFAULT 'ai_sql';")
                changes.append("added query_audit_log.query_type")
            if "scope" not in qa_cols:
                conn.execute("ALTER TABLE query_audit_log ADD COLUMN scope TEXT NOT NULL DEFAULT 'self';")
                changes.append("added query_audit_log.scope")
            if "success" not in qa_cols:
                conn.execute("ALTER TABLE query_audit_log ADD COLUMN success INTEGER NOT NULL DEFAULT 1;")
                changes.append("added query_audit_log.success")

    # 3. Add requires_executive_approval to leave_requests + refresh v_leave_requests
    if _sqlite_table_exists(conn, "leave_requests"):
        lr_cols = _sqlite_column_names(conn, "leave_requests")
        if "requires_executive_approval" not in lr_cols:
            conn.execute(
                "ALTER TABLE leave_requests ADD COLUMN requires_executive_approval INTEGER NOT NULL DEFAULT 0 CHECK (requires_executive_approval IN (0, 1));"
            )
            changes.append("added leave_requests.requires_executive_approval")
        conn.execute("DROP VIEW IF EXISTS v_employees;")
        conn.execute("DROP VIEW IF EXISTS v_attendance_daily;")
        conn.execute("DROP VIEW IF EXISTS v_leave_requests;")
        conn.execute("DROP VIEW IF EXISTS v_anomalies;")
        conn.execute(
            """
            CREATE VIEW v_employees AS
            SELECT
                e.employee_id, e.full_name, e.department_id, d.name AS department_name,
                e.position, e.manager_id, m.full_name AS manager_name,
                e.start_date, e.annual_leave_balance, e.role, e.employment_status
            FROM employees e
            JOIN departments d ON d.department_id = e.department_id
            LEFT JOIN employees m ON m.employee_id = e.manager_id;
            """
        )
        if _sqlite_table_exists(conn, "attendance") and _sqlite_table_exists(conn, "holidays"):
            conn.execute(
                """
                CREATE VIEW v_attendance_daily AS
                SELECT
                    a.id, a.employee_id, e.full_name, e.department_id, d.name AS department_name,
                    a.work_date, substr(a.work_date, 1, 7) AS period, a.check_in, a.check_out, a.status, a.source,
                    CASE
                        WHEN a.status = 'present' AND a.check_in IS NOT NULL
                             AND (julianday(a.check_in) - julianday(a.work_date || ' 08:30:00')) * 1440.0 > 5.0
                        THEN CAST(ROUND((julianday(a.check_in) - julianday(a.work_date || ' 08:30:00')) * 1440.0) AS INTEGER)
                        ELSE 0
                    END AS late_minutes,
                    CASE
                        WHEN a.status = 'present' AND a.check_in IS NOT NULL
                             AND (julianday(a.check_in) - julianday(a.work_date || ' 08:30:00')) * 1440.0 > 5.0
                        THEN 1 ELSE 0
                    END AS is_late,
                    CASE
                        WHEN a.status = 'present' AND a.check_in IS NOT NULL AND a.check_out IS NOT NULL THEN
                            ROUND(MAX(0.0, (julianday(a.check_out) - julianday(a.check_in)) * 24.0
                                - CASE WHEN (julianday(a.check_out) - julianday(a.check_in)) * 24.0 > 5.0 THEN 1.0 ELSE 0.0 END), 2)
                        ELSE 0.0
                    END AS work_hours,
                    CASE WHEN CAST(strftime('%w', a.work_date) AS INTEGER) IN (0, 6) THEN 1 ELSE 0 END AS is_weekend,
                    CASE WHEN h.holiday_date IS NOT NULL THEN 1 ELSE 0 END AS is_holiday
                FROM attendance a
                JOIN employees e ON e.employee_id = a.employee_id
                JOIN departments d ON d.department_id = e.department_id
                LEFT JOIN holidays h ON h.holiday_date = a.work_date;
                """
            )
        conn.execute(
            """
            CREATE VIEW v_leave_requests AS
            SELECT
                lr.request_id,
                lr.employee_id,
                e.full_name,
                e.department_id,
                d.name AS department_name,
                lr.leave_type,
                lr.from_date,
                lr.to_date,
                substr(lr.from_date, 1, 7) AS period,
                CAST(julianday(lr.to_date) - julianday(lr.from_date) + 1 AS INTEGER) AS leave_days,
                lr.reason,
                lr.status,
                lr.requires_executive_approval,
                lr.reviewed_by,
                lr.reviewed_at,
                lr.decision_note,
                lr.created_at
            FROM leave_requests lr
            JOIN employees e ON e.employee_id = lr.employee_id
            JOIN departments d ON d.department_id = e.department_id;
            """
        )
        if _sqlite_table_exists(conn, "anomalies"):
            conn.execute(
                """
                CREATE VIEW v_anomalies AS
                SELECT
                    an.anomaly_id, an.employee_id, e.full_name,
                    COALESCE(an.department_id, e.department_id) AS department_id,
                    d.name AS department_name, an.scope_type, an.rule_code, an.anomaly_type,
                    an.severity, an.period, an.evidence, an.explanation, an.review_status,
                    an.reviewed_by, an.reviewed_at, an.review_note, an.detected_at
                FROM anomalies an
                LEFT JOIN employees e ON e.employee_id = an.employee_id
                LEFT JOIN departments d ON d.department_id = COALESCE(an.department_id, e.department_id);
                """
            )

    # 4. Create normalized RBAC & Admin technical tables if not exist
    ddl_statements = [
        """
        CREATE TABLE IF NOT EXISTS roles (
            role_id INTEGER PRIMARY KEY AUTOINCREMENT,
            role_code TEXT NOT NULL UNIQUE CHECK (role_code IN ('employee', 'manager', 'hr', 'executive', 'admin')),
            role_name TEXT NOT NULL,
            description TEXT NULL,
            is_system_role INTEGER NOT NULL DEFAULT 1 CHECK (is_system_role IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS permissions (
            permission_id INTEGER PRIMARY KEY AUTOINCREMENT,
            permission_code TEXT NOT NULL UNIQUE,
            permission_name TEXT NOT NULL,
            description TEXT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS user_roles (
            user_id TEXT NOT NULL,
            role_id INTEGER NOT NULL,
            assigned_by_user_id TEXT NULL,
            assigned_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
            PRIMARY KEY (user_id, role_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE CASCADE,
            FOREIGN KEY (role_id) REFERENCES roles(role_id) ON UPDATE CASCADE ON DELETE RESTRICT,
            FOREIGN KEY (assigned_by_user_id) REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS role_permissions (
            role_id INTEGER NOT NULL,
            permission_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
            PRIMARY KEY (role_id, permission_id),
            FOREIGN KEY (role_id) REFERENCES roles(role_id) ON UPDATE CASCADE ON DELETE CASCADE,
            FOREIGN KEY (permission_id) REFERENCES permissions(permission_id) ON UPDATE CASCADE ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS system_settings (
            setting_key TEXT PRIMARY KEY,
            category TEXT NOT NULL DEFAULT 'general',
            setting_value TEXT NOT NULL,
            value_type TEXT NOT NULL DEFAULT 'string',
            description TEXT NULL,
            updated_by_user_id TEXT NULL,
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
            FOREIGN KEY (updated_by_user_id) REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS revoked_tokens (
            jti TEXT PRIMARY KEY,
            user_id TEXT NULL,
            revoked_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
            expires_at TEXT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE SET NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_revoked_tokens_expires ON revoked_tokens(expires_at);",
        """
        CREATE TABLE IF NOT EXISTS kiosk_devices (
            kiosk_device_id TEXT PRIMARY KEY,
            device_name TEXT NOT NULL,
            location_name TEXT NULL,
            branch_name TEXT NULL,
            assigned_user_id TEXT NULL,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            last_seen_at TEXT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
            FOREIGN KEY (assigned_user_id) REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS company_documents (
            document_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            original_file_name TEXT NOT NULL,
            storage_bucket TEXT NOT NULL DEFAULT 'hr-documents',
            storage_path TEXT NOT NULL UNIQUE,
            document_type TEXT NOT NULL DEFAULT 'policy',
            version_label TEXT NULL,
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('processing', 'active', 'archived', 'failed')),
            checksum_sha256 TEXT NULL,
            uploaded_by_user_id TEXT NULL,
            uploaded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
            processed_at TEXT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (uploaded_by_user_id) REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS document_chunks (
            chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
            content TEXT NOT NULL,
            embedding_model TEXT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
            UNIQUE (document_id, chunk_index),
            FOREIGN KEY (document_id) REFERENCES company_documents(document_id) ON UPDATE CASCADE ON DELETE CASCADE
        )
        """,
    ]
    for stmt in ddl_statements:
        conn.execute(stmt)

    rag_changes = ensure_rag_phase2_schema(conn)
    changes.extend(rag_changes.get("changes", []))
    p3_changes = ensure_ai_phase3_schema(conn)
    changes.extend(p3_changes.get("changes", []))
    return {"engine": "sqlite", "changes": changes}


def ensure_ai_phase3_schema(conn: Any) -> Dict[str, Any]:
    """Non-destructively create user-isolated AI conversation tables for Phase 3 (SQLite & Supabase PG).

    Zero duplicate tables, zero data loss, 100% idempotent, immediate RLS + REVOKE on Supabase PostgreSQL.
    Reversible rollback (PostgreSQL):
        DROP TABLE IF EXISTS public.ai_messages;
        DROP TABLE IF EXISTS public.ai_conversations;
    """
    changes: List[str] = []
    if is_postgres_connection(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS public.ai_conversations (
                conversation_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES public.users(user_id)
                    ON UPDATE CASCADE ON DELETE CASCADE,
                title TEXT NOT NULL,
                context_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS public.ai_messages (
                message_id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES public.ai_conversations(conversation_id)
                    ON UPDATE CASCADE ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES public.users(user_id)
                    ON UPDATE CASCADE ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                route_type TEXT,
                response_json JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_conversations_user_updated ON public.ai_conversations(user_id, updated_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_messages_conv_id ON public.ai_messages(conversation_id, message_id ASC)"
        )
        conn.execute("ALTER TABLE public.ai_conversations ENABLE ROW LEVEL SECURITY")
        conn.execute("ALTER TABLE public.ai_messages ENABLE ROW LEVEL SECURITY")
        conn.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                    REVOKE ALL ON TABLE public.ai_conversations, public.ai_messages FROM anon;
                END IF;
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                    REVOKE ALL ON TABLE public.ai_conversations, public.ai_messages FROM authenticated;
                END IF;
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
                    GRANT ALL ON TABLE public.ai_conversations, public.ai_messages TO service_role;
                    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO service_role;
                END IF;
            END;
            $$
            """
        )
        changes.append("ensured public.ai_conversations & public.ai_messages (RLS + least privilege)")
        return {"engine": "postgresql", "changes": changes}

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_conversations (
            conversation_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            context_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_messages (
            message_id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            route_type TEXT NULL,
            response_json TEXT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
            FOREIGN KEY (conversation_id) REFERENCES ai_conversations(conversation_id) ON UPDATE CASCADE ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON UPDATE CASCADE ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_conversations_user_updated ON ai_conversations(user_id, updated_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_messages_conv_id ON ai_messages(conversation_id, message_id)"
    )
    changes.append("ensured sqlite ai_conversations & ai_messages")
    return {"engine": "sqlite", "changes": changes}


def ensure_rag_phase2_schema(conn: Any) -> Dict[str, Any]:
    """Non-destructively upgrade company_documents & document_chunks for Phase 2 RAG (SQLite & Supabase PG).

    Zero duplicate tables, zero data loss, 100% idempotent.
    Reversible rollback (PostgreSQL):
        ALTER TABLE public.company_documents
          DROP COLUMN IF EXISTS supersedes_document_id,
          DROP COLUMN IF EXISTS is_current,
          DROP COLUMN IF EXISTS effective_to,
          DROP COLUMN IF EXISTS effective_from,
          DROP COLUMN IF EXISTS visibility,
          DROP COLUMN IF EXISTS source_content;
        ALTER TABLE public.document_chunks DROP COLUMN IF EXISTS embedding_dim;
    """
    changes: List[str] = []
    if is_postgres_connection(conn):
        pg_alters = [
            ("source_content", "ALTER TABLE public.company_documents ADD COLUMN IF NOT EXISTS source_content TEXT"),
            ("visibility", "ALTER TABLE public.company_documents ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'all'"),
            ("effective_from", "ALTER TABLE public.company_documents ADD COLUMN IF NOT EXISTS effective_from DATE"),
            ("effective_to", "ALTER TABLE public.company_documents ADD COLUMN IF NOT EXISTS effective_to DATE"),
            ("is_current", "ALTER TABLE public.company_documents ADD COLUMN IF NOT EXISTS is_current SMALLINT NOT NULL DEFAULT 1"),
            (
                "supersedes_document_id",
                "ALTER TABLE public.company_documents ADD COLUMN IF NOT EXISTS supersedes_document_id BIGINT REFERENCES public.company_documents(document_id) ON UPDATE CASCADE ON DELETE SET NULL",
            ),
            ("embedding_dim", "ALTER TABLE public.document_chunks ADD COLUMN IF NOT EXISTS embedding_dim INTEGER"),
        ]
        for label, stmt in pg_alters:
            conn.execute(stmt)
            changes.append(f"ensured pg column {label}")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_company_documents_active_vis ON public.company_documents(status, is_current, visibility)"
        )
        conn.execute("ALTER TABLE public.company_documents ENABLE ROW LEVEL SECURITY")
        conn.execute("ALTER TABLE public.document_chunks ENABLE ROW LEVEL SECURITY")
        return {"engine": "postgresql", "changes": changes}

    if _sqlite_table_exists(conn, "company_documents"):
        doc_cols = _sqlite_column_names(conn, "company_documents")
        sqlite_doc_alters = [
            ("source_content", "ALTER TABLE company_documents ADD COLUMN source_content TEXT NULL"),
            ("visibility", "ALTER TABLE company_documents ADD COLUMN visibility TEXT NOT NULL DEFAULT 'all'"),
            ("effective_from", "ALTER TABLE company_documents ADD COLUMN effective_from TEXT NULL"),
            ("effective_to", "ALTER TABLE company_documents ADD COLUMN effective_to TEXT NULL"),
            ("is_current", "ALTER TABLE company_documents ADD COLUMN is_current INTEGER NOT NULL DEFAULT 1"),
            ("supersedes_document_id", "ALTER TABLE company_documents ADD COLUMN supersedes_document_id INTEGER NULL"),
        ]
        for col, stmt in sqlite_doc_alters:
            if col not in doc_cols:
                conn.execute(stmt)
                changes.append(f"added company_documents.{col}")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_company_documents_active_vis ON company_documents(status, is_current, visibility)"
        )

    if _sqlite_table_exists(conn, "document_chunks"):
        chk_cols = _sqlite_column_names(conn, "document_chunks")
        if "embedding_json" not in chk_cols:
            conn.execute("ALTER TABLE document_chunks ADD COLUMN embedding_json TEXT NULL")
            changes.append("added document_chunks.embedding_json")
        if "embedding_dim" not in chk_cols:
            conn.execute("ALTER TABLE document_chunks ADD COLUMN embedding_dim INTEGER NULL")
            changes.append("added document_chunks.embedding_dim")

    return {"engine": "sqlite", "changes": changes}


def _ensure_postgres_rbac_schema(conn: Any) -> Dict[str, Any]:
    """Non-destructively add missing 5-role RBAC columns & tables on Supabase PostgreSQL."""
    changes: List[str] = []

    conn.execute(
        """
        ALTER TABLE public.leave_requests
        ADD COLUMN IF NOT EXISTS requires_executive_approval SMALLINT NOT NULL DEFAULT 0
        CHECK (requires_executive_approval IN (0, 1))
        """
    )
    conn.execute(
        """
        ALTER TABLE public.query_audit_log
        ADD COLUMN IF NOT EXISTS query_type TEXT NOT NULL DEFAULT 'ai_sql'
        """
    )
    conn.execute(
        """
        ALTER TABLE public.query_audit_log
        ADD COLUMN IF NOT EXISTS scope TEXT NOT NULL DEFAULT 'self'
        """
    )
    conn.execute(
        """
        ALTER TABLE public.query_audit_log
        ADD COLUMN IF NOT EXISTS success SMALLINT NOT NULL DEFAULT 1
        CHECK (success IN (0, 1))
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS public.system_settings (
            setting_key TEXT PRIMARY KEY,
            category TEXT NOT NULL DEFAULT 'general',
            setting_value TEXT NOT NULL,
            value_type TEXT NOT NULL DEFAULT 'string',
            description TEXT,
            updated_by_user_id TEXT REFERENCES public.users(user_id)
                ON UPDATE CASCADE ON DELETE SET NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS public.revoked_tokens (
            jti TEXT PRIMARY KEY,
            user_id TEXT REFERENCES public.users(user_id)
                ON UPDATE CASCADE ON DELETE SET NULL,
            revoked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_revoked_tokens_expires ON public.revoked_tokens(expires_at)")
    conn.execute("ALTER TABLE public.system_settings ENABLE ROW LEVEL SECURITY")
    conn.execute("ALTER TABLE public.revoked_tokens ENABLE ROW LEVEL SECURITY")
    conn.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL ON TABLE public.system_settings, public.revoked_tokens FROM anon;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                REVOKE ALL ON TABLE public.system_settings, public.revoked_tokens FROM authenticated;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
                GRANT ALL ON TABLE public.system_settings, public.revoked_tokens TO service_role;
            END IF;
        END;
        $$
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE VIEW public.v_leave_requests AS
        SELECT
            lr.request_id,
            lr.employee_id,
            e.full_name,
            e.department_id,
            d.name AS department_name,
            lr.leave_type,
            lr.from_date,
            lr.to_date,
            TO_CHAR(lr.from_date, 'YYYY-MM') AS period,
            (lr.to_date - lr.from_date + 1)::INTEGER AS leave_days,
            lr.reason,
            lr.status,
            lr.reviewed_by,
            reviewer.full_name AS reviewer_name,
            lr.reviewed_at,
            lr.decision_note,
            lr.created_at,
            lr.requires_executive_approval
        FROM public.leave_requests lr
        JOIN public.employees e ON e.employee_id = lr.employee_id
        JOIN public.departments d ON d.department_id = e.department_id
        LEFT JOIN public.employees reviewer ON reviewer.employee_id = lr.reviewed_by
        """
    )
    conn.execute("ALTER VIEW public.v_leave_requests SET (security_invoker = true)")
    rag_pg = ensure_rag_phase2_schema(conn)
    changes.extend(rag_pg.get("changes", []))
    p3_pg = ensure_ai_phase3_schema(conn)
    changes.extend(p3_pg.get("changes", []))
    changes.append(
        "ensured requires_executive_approval, query_audit_log extensions, system_settings (RLS), revoked_tokens (RLS), ai_conversations/ai_messages (RLS), v_leave_requests on PostgreSQL"
    )
    return {"engine": "postgresql", "changes": changes}


def seed_rbac_and_system_defaults(conn: Any, sync_strict_role_matrix: bool = False) -> Dict[str, int]:
    """Idempotently populate roles, permissions, role_permissions, user_roles, system_settings, kiosk_devices & RAG docs."""
    pg = is_postgres_connection(conn)

    # 1. Roles (5 enterprise roles)
    for role_code, role_name, desc in ROLE_CATALOG:
        if pg:
            conn.execute(
                """
                INSERT INTO public.roles (role_code, role_name, description)
                VALUES (?, ?, ?)
                ON CONFLICT (role_code) DO UPDATE SET role_name = EXCLUDED.role_name, description = EXCLUDED.description
                """,
                (role_code, role_name, desc),
            )
        else:
            conn.execute(
                """
                INSERT OR IGNORE INTO roles (role_code, role_name, description, is_system_role)
                VALUES (?, ?, ?, 1)
                """,
                (role_code, role_name, desc),
            )

    # 2. Permissions
    for perm_code, perm_name, desc in PERMISSION_CATALOG:
        if pg:
            conn.execute(
                """
                INSERT INTO public.permissions (permission_code, permission_name, description)
                VALUES (?, ?, ?)
                ON CONFLICT (permission_code) DO UPDATE SET permission_name = EXCLUDED.permission_name, description = EXCLUDED.description
                """,
                (perm_code, perm_name, desc),
            )
        else:
            conn.execute(
                """
                INSERT OR IGNORE INTO permissions (permission_code, permission_name, description)
                VALUES (?, ?, ?)
                """,
                (perm_code, perm_name, desc),
            )

    role_ids = {
        r["role_code"]: r["role_id"]
        for r in conn.execute("SELECT role_id, role_code FROM roles").fetchall()
    }
    perm_ids = {
        r["permission_code"]: r["permission_id"]
        for r in conn.execute("SELECT permission_id, permission_code FROM permissions").fetchall()
    }

    # 3. Role -> Permissions mappings
    if sync_strict_role_matrix:
        legacy_removals = [
            ("admin", "employee.read.all"),
            ("admin", "policy.manage"),
            ("hr", "account.manage"),
            ("hr", "audit.read"),
            ("hr", "kiosk.manage"),
        ]
        for r_code, p_code in legacy_removals:
            if r_code in role_ids and p_code in perm_ids:
                conn.execute(
                    "DELETE FROM role_permissions WHERE role_id = ? AND permission_id = ?",
                    (role_ids[r_code], perm_ids[p_code]),
                )

    mapping_count = 0
    for role_code, perms in DEFAULT_ROLE_PERMISSIONS.items():
        rid = role_ids.get(role_code)
        if not rid:
            continue
        for perm_code in perms:
            pid = perm_ids.get(perm_code)
            if not pid:
                continue
            if pg:
                conn.execute(
                    """
                    INSERT INTO public.role_permissions (role_id, permission_id)
                    VALUES (?, ?)
                    ON CONFLICT (role_id, permission_id) DO NOTHING
                    """,
                    (rid, pid),
                )
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO role_permissions (role_id, permission_id) VALUES (?, ?)",
                    (rid, pid),
                )
            mapping_count += 1

    # 4. Sync user_roles cleanly with employees.role
    users_with_roles = conn.execute(
        """
        SELECT u.user_id, e.role
        FROM users u
        JOIN employees e ON e.employee_id = u.employee_id
        """
    ).fetchall()
    for row in users_with_roles:
        rid = role_ids.get(row["role"])
        if not rid:
            continue
        existing = conn.execute(
            "SELECT role_id FROM user_roles WHERE user_id = ?",
            (row["user_id"],),
        ).fetchall()
        existing_rids = {e["role_id"] for e in existing}
        if rid not in existing_rids:
            conn.execute("DELETE FROM user_roles WHERE user_id = ?", (row["user_id"],))
            if pg:
                conn.execute(
                    """
                    INSERT INTO public.user_roles (user_id, role_id)
                    VALUES (?, ?)
                    ON CONFLICT (user_id, role_id) DO NOTHING
                    """,
                    (row["user_id"], rid),
                )
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)",
                    (row["user_id"], rid),
                )

    # 5. Default system settings (non-secret technical settings only)
    for key, cat, val, vtype, desc in DEFAULT_SYSTEM_SETTINGS:
        if pg:
            conn.execute(
                """
                INSERT INTO public.system_settings (setting_key, category, setting_value, value_type, description)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (setting_key) DO NOTHING
                """,
                (key, cat, val, vtype, desc),
            )
        else:
            conn.execute(
                """
                INSERT OR IGNORE INTO system_settings (setting_key, category, setting_value, value_type, description)
                VALUES (?, ?, ?, ?, ?)
                """,
                (key, cat, val, vtype, desc),
            )

    # 6. Default Kiosk devices
    for dev_id, name, loc, branch, is_act in DEFAULT_KIOSK_DEVICES:
        if pg:
            conn.execute(
                """
                INSERT INTO public.kiosk_devices (kiosk_device_id, device_name, location_name, branch_name, is_active)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (kiosk_device_id) DO NOTHING
                """,
                (dev_id, name, loc, branch, bool(is_act)),
            )
        else:
            conn.execute(
                """
                INSERT OR IGNORE INTO kiosk_devices (kiosk_device_id, device_name, location_name, branch_name, is_active)
                VALUES (?, ?, ?, ?, ?)
                """,
                (dev_id, name, loc, branch, is_act),
            )

    # 7. Default RAG documents metadata + sample chunks
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    admin_user = conn.execute("SELECT user_id FROM users WHERE LOWER(username) = 'admin@company.vn'").fetchone()
    uploader_id = admin_user["user_id"] if admin_user else None

    for title, fname, bucket, spath, dtype, ver, dstatus in DEFAULT_RAG_DOCUMENTS:
        existing_doc = conn.execute(
            "SELECT document_id FROM company_documents WHERE storage_path = ?",
            (spath,),
        ).fetchone()
        if not existing_doc:
            meta_val = json.dumps({"source": "seed", "chunks_indexed": 1}, ensure_ascii=False)
            if pg:
                cur = conn.execute(
                    """
                    INSERT INTO public.company_documents (
                        title, original_file_name, storage_bucket, storage_path, document_type,
                        version_label, status, uploaded_by_user_id, processed_at, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?::jsonb)
                    """,
                    (title, fname, bucket, spath, dtype, ver, dstatus, uploader_id, now_str, meta_val),
                )
                doc_id = cur.lastrowid
                if doc_id:
                    conn.execute(
                        """
                        INSERT INTO public.document_chunks (document_id, chunk_index, content, embedding_model, metadata)
                        VALUES (?, 0, ?, 'local_bm25_hybrid', '{"section": "summary"}'::jsonb)
                        ON CONFLICT (document_id, chunk_index) DO NOTHING
                        """,
                        (doc_id, f"{title}: Tài liệu chuẩn doanh nghiệp phiên bản {ver} đã được nạp vào kho tri thức RAG."),
                    )
            else:
                cur = conn.execute(
                    """
                    INSERT INTO company_documents (
                        title, original_file_name, storage_bucket, storage_path, document_type,
                        version_label, status, uploaded_by_user_id, processed_at, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (title, fname, bucket, spath, dtype, ver, dstatus, uploader_id, now_str, meta_val),
                )
                doc_id = cur.lastrowid
                if doc_id:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO document_chunks (document_id, chunk_index, content, embedding_model, metadata)
                        VALUES (?, 0, ?, 'local_bm25_hybrid', '{"section": "summary"}')
                        """,
                        (doc_id, f"{title}: Tài liệu chuẩn doanh nghiệp phiên bản {ver} đã được nạp vào kho tri thức RAG."),
                    )

    # Upgrade stub seed documents cleanly into structured, embedded Vietnamese HR policies (never touches user docs)
    ensure_rag_phase2_schema(conn)
    ensure_ai_phase3_schema(conn)
    from app.services.ai_rag_service import upgrade_placeholder_seed_documents

    upgrade_placeholder_seed_documents(conn)

    return {
        "roles": len(role_ids),
        "permissions": len(perm_ids),
        "role_permissions_seeded": mapping_count,
    }


def ensure_seed_executive_and_admin_accounts(conn: Any) -> Dict[str, str]:
    """Safely ensure director@company.vn (executive) and admin@company.vn (admin) exist without losing data."""
    result: Dict[str, str] = {}
    targets = [
        ("director@company.vn", "NV079", "USR079", "Trần Minh Quang", "Giám đốc Điều hành", "executive", "0901000079"),
        ("admin@company.vn", "NV080", "USR080", "Nguyễn Hải Đăng", "Quản trị viên Hệ thống", "admin", "0901000080"),
    ]
    pwd_hash = bcrypt.hashpw(DEV_DEFAULT_PASSWORD.encode("utf-8"), bcrypt.gensalt(rounds=4)).decode("utf-8")

    for email, emp_id, user_id, full_name, position, role_code, phone in targets:
        existing_user = conn.execute(
            "SELECT user_id, employee_id FROM users WHERE LOWER(username) = ?",
            (email,),
        ).fetchone()
        if existing_user:
            conn.execute(
                "UPDATE employees SET role = ?, position = ?, manager_id = NULL WHERE employee_id = ?",
                (role_code, position, existing_user["employee_id"]),
            )
            result[email] = f"verified ({existing_user['employee_id']} -> {role_code})"
            continue

        existing_emp = conn.execute(
            "SELECT employee_id FROM employees WHERE employee_id = ?",
            (emp_id,),
        ).fetchone()
        if existing_emp:
            conn.execute(
                """
                UPDATE employees
                SET full_name = ?, position = ?, manager_id = NULL, role = ?, email = ?, phone = ?, employment_status = 'active'
                WHERE employee_id = ?
                """,
                (full_name, position, role_code, email, phone, emp_id),
            )
            linked_user = conn.execute(
                "SELECT user_id FROM users WHERE employee_id = ?",
                (emp_id,),
            ).fetchone()
            if linked_user:
                conn.execute(
                    "UPDATE users SET username = ?, is_active = 1 WHERE user_id = ?",
                    (email, linked_user["user_id"]),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO users (user_id, username, password_hash, employee_id, is_active, must_change_password)
                    VALUES (?, ?, ?, ?, 1, 0)
                    """,
                    (user_id, email, pwd_hash, emp_id),
                )
            result[email] = f"upgraded {emp_id} -> {role_code}"
        else:
            conn.execute(
                """
                INSERT INTO employees (
                    employee_id, full_name, department_id, position, manager_id,
                    start_date, annual_leave_balance, role, employment_status, email, phone
                ) VALUES (?, ?, 'DEPT_OPS', ?, NULL, '2023-01-01', 12.0, ?, 'active', ?, ?)
                """,
                (emp_id, full_name, position, role_code, email, phone),
            )
            conn.execute(
                """
                INSERT INTO users (user_id, username, password_hash, employee_id, is_active, must_change_password)
                VALUES (?, ?, ?, ?, 1, 0)
                """,
                (user_id, email, pwd_hash, emp_id),
            )
            result[email] = f"created {emp_id} -> {role_code}"

    has_exec_leave = conn.execute(
        "SELECT 1 FROM leave_requests WHERE requires_executive_approval = 1 LIMIT 1"
    ).fetchone()
    if not has_exec_leave:
        conn.execute(
            """
            UPDATE leave_requests
            SET requires_executive_approval = 1
            WHERE request_id = (
                SELECT request_id FROM leave_requests
                WHERE employee_id = 'NV068' AND status = 'pending'
                ORDER BY request_id ASC
                LIMIT 1
            )
            """
        )

    return result


def migrate_rbac_5_roles(
    db_path: Optional[Path | str] = None,
    seed_demo_accounts: bool = True,
) -> Dict[str, Any]:
    """Run non-destructive 5-role RBAC migration on either SQLite or configured PostgreSQL (Supabase)."""
    conn = get_connection(db_path=db_path, readonly=False)
    try:
        if is_postgres_connection(conn):
            schema_res = _ensure_postgres_rbac_schema(conn)
        else:
            schema_res = _ensure_sqlite_rbac_schema(conn)

        account_res: Dict[str, str] = {}
        if seed_demo_accounts and os.getenv("APP_ENV", "development").lower() != "production":
            account_res = ensure_seed_executive_and_admin_accounts(conn)

        rbac_res = seed_rbac_and_system_defaults(conn, sync_strict_role_matrix=True)
        conn.commit()
        return {
            "schema": schema_res,
            "accounts": account_res,
            "rbac": rbac_res,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def migrate_rag_phase2(
    db_path: Optional[Path | str] = None,
    upgrade_placeholders: bool = True,
) -> Dict[str, Any]:
    """Run non-destructive Phase 2 RAG schema migration & idempotent seed doc indexing on SQLite or Supabase PG."""
    conn = get_connection(db_path=db_path, readonly=False)
    try:
        schema_res = ensure_rag_phase2_schema(conn)
        seed_res: Dict[str, Any] = {"upgraded": [], "skipped": []}
        if upgrade_placeholders:
            from app.services.ai_rag_service import upgrade_placeholder_seed_documents

            seed_res = upgrade_placeholder_seed_documents(conn)
        conn.commit()
        return {"schema": schema_res, "documents": seed_res}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def migrate_ai_phase3(db_path: Optional[Path | str] = None) -> Dict[str, Any]:
    """Run non-destructive Phase 3 AI Conversation schema migration on SQLite or Supabase PG."""
    conn = get_connection(db_path=db_path, readonly=False)
    try:
        schema_res = ensure_ai_phase3_schema(conn)
        conn.commit()
        return {"schema": schema_res}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Non-destructive 5-role RBAC database migration")
    parser.add_argument("--db", type=str, default=None, help="Optional SQLite DB path (defaults to DATABASE_URL)")
    parser.add_argument("--no-seed-accounts", action="store_true", help="Skip creating/upgrading dev admin & director accounts")
    args = parser.parse_args()
    summary = migrate_rbac_5_roles(db_path=args.db, seed_demo_accounts=not args.no_seed_accounts)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
