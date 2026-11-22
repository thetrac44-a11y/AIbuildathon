from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.security import AuthenticatedUser
from app.db.connection import get_connection
from app.schemas.common import RoleEnum

ALLOWED_VIEWS = {
    "v_employees",
    "v_attendance_daily",
    "v_leave_requests",
    "v_anomalies",
}

ALLOWED_VIEW_COLUMNS: Dict[str, set[str]] = {
    "v_employees": {
        "employee_id", "full_name", "department_id", "department_name", "position",
        "manager_id", "manager_name", "start_date", "annual_leave_balance", "role", "employment_status",
    },
    "v_attendance_daily": {
        "id", "employee_id", "full_name", "department_id", "department_name", "work_date",
        "period", "check_in", "check_out", "status", "source", "late_minutes", "is_late",
        "work_hours", "is_weekend", "is_holiday",
    },
    "v_leave_requests": {
        "request_id", "employee_id", "full_name", "department_id", "department_name",
        "leave_type", "from_date", "to_date", "period", "leave_days", "reason", "status",
        "reviewed_by", "reviewed_at", "decision_note", "created_at",
    },
    "v_anomalies": {
        "anomaly_id", "employee_id", "full_name", "department_id", "department_name",
        "scope_type", "rule_code", "anomaly_type", "severity", "period", "evidence",
        "explanation", "review_status", "reviewed_by", "reviewed_at", "review_note", "detected_at",
    },
}

FORBIDDEN_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "create", "replace",
    "attach", "detach", "pragma", "vacuum", "reindex", "load_extension",
    "truncate", "grant", "revoke", "commit", "rollback", "begin", "savepoint",
    "exec", "execute",
}

FORBIDDEN_IDENTIFIERS = {
    # Sensitive / system / audit tables
    "users", "password_hash", "sqlite_master", "sqlite_schema", "sqlite_temp_master",
    "sqlite_sequence", "activity_logs", "query_audit_log", "import_logs",
    "leave_approval_logs", "main", "temp",
    # Raw base tables (must NEVER be queried directly; only the 4 RBAC-scoped v_* TEMP views are allowed)
    "employees", "attendance", "leave_requests", "anomalies",
    "departments", "holidays", "overtime_requests",
    # Sensitive employee PII excluded from v_employees
    "email", "phone",
}


class SQLGuardError(ValueError):
    """Raised whenever a SQL query violates security or allowlist policy."""


def validate_readonly_sql(sql: str, max_rows: int = 200) -> str:
    """Strictly validate SQL text: SELECT-only on allowlisted views, single statement, no comments/DDL, enforce LIMIT."""
    if not sql or not sql.strip():
        raise SQLGuardError("Câu lệnh SQL rỗng.")

    cleaned = sql.strip()

    # Block SQL comments (often used to obfuscate injection)
    if "--" in cleaned or "/*" in cleaned or "*/" in cleaned:
        raise SQLGuardError("Không cho phép chứa chú thích SQL (-- hoặc /* */).")

    # Strip single trailing semicolon, then forbid any remaining semicolons (multi-statement)
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].strip()
    if ";" in cleaned:
        raise SQLGuardError("Không cho phép thực thi nhiều câu lệnh SQL cùng lúc.")

    # Must start with SELECT or WITH
    first_word_match = re.match(r"^\s*([a-zA-Z_]+)", cleaned)
    if not first_word_match or first_word_match.group(1).lower() not in ("select", "with"):
        raise SQLGuardError("Chỉ cho phép câu lệnh truy vấn đọc SELECT.")

    # Strip single-quoted string literals before lexical inspection
    no_strings = re.sub(r"'[^']*'", "''", cleaned)

    # Block quoted/bracketed identifiers ("...", `...`, [...]) that could evade FROM/JOIN regex checks
    if any(ch in no_strings for ch in ('"', "`", "[", "]")):
        raise SQLGuardError("Không cho phép dùng định danh bọc dấu ngoặc (\", `, [ ]). Chỉ truy vấn trực tiếp 4 view hợp lệ.")

    # Block comma-separated FROM joins (e.g. FROM v_employees, employees)
    if re.search(r"\bfrom\s+[a-zA-Z_][a-zA-Z0-9_]*(?:\s+(?:as\s+)?[a-zA-Z_][a-zA-Z0-9_]*)?\s*,", no_strings, flags=re.IGNORECASE):
        raise SQLGuardError("Không cho phép cú pháp comma-join trong FROM. Hãy dùng JOIN tường minh giữa các view hợp lệ.")

    tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", no_strings)
    lower_tokens = [t.lower() for t in tokens]

    for kw in FORBIDDEN_KEYWORDS:
        if kw in lower_tokens:
            raise SQLGuardError(f"Từ khóa SQL không được phép: {kw.upper()}.")

    for ident in FORBIDDEN_IDENTIFIERS:
        if ident in lower_tokens:
            raise SQLGuardError(f"Đối tượng hoặc cột dữ liệu không nằm trong danh sách cho phép: {ident}.")

    # Extract all referenced table/view names after FROM or JOIN
    referenced = re.findall(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_\.]*)", no_strings, flags=re.IGNORECASE)
    if not referenced:
        raise SQLGuardError("Truy vấn phải tham chiếu ít nhất một view hợp lệ.")

    # Collect CTE names if WITH is used so CTEs are allowed as FROM targets
    cte_names = {
        m.lower()
        for m in re.findall(r"\b(?:with|,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s+as\s*\(", no_strings, flags=re.IGNORECASE)
    }

    for ref in referenced:
        ref_l = ref.lower()
        if "." in ref_l:
            raise SQLGuardError(f"Không cho phép truy cập trực tiếp schema/prefix: {ref}.")
        if ref_l not in ALLOWED_VIEWS and ref_l not in cte_names:
            raise SQLGuardError(f"Bảng/view '{ref}' không nằm trong allowlist an toàn cho AI.")

    # Enforce outer row limit <= max_rows (match strictly at the end of the outer query)
    limit_match = re.search(r"\blimit\s+(\d+)(?:\s+offset\s+\d+)?\s*$", no_strings, flags=re.IGNORECASE)
    if limit_match:
        requested_limit = int(limit_match.group(1))
        if requested_limit > max_rows:
            cleaned = re.sub(
                r"\blimit\s+\d+(\s+offset\s+\d+)?\s*$",
                lambda m: f"LIMIT {max_rows}{m.group(1) or ''}",
                cleaned,
                count=1,
                flags=re.IGNORECASE,
            )
    else:
        cleaned = f"{cleaned} LIMIT {max_rows}"

    return cleaned


def _create_scoped_temp_views(conn: sqlite3.Connection, user: AuthenticatedUser) -> None:
    """Create TEMP views shadowing the 4 allowlisted views with hard-coded RBAC scope for the authenticated user."""
    if user.role == RoleEnum.hr:
        emp_cond = "1 = 1"
        att_cond = "1 = 1"
        leave_cond = "1 = 1"
        anom_cond = "1 = 1"
    elif user.role == RoleEnum.manager:
        dept = user.department_id.replace("'", "''")
        emp_cond = f"department_id = '{dept}'"
        att_cond = f"department_id = '{dept}'"
        leave_cond = f"department_id = '{dept}'"
        anom_cond = f"department_id = '{dept}'"
    else:
        emp = user.employee_id.replace("'", "''")
        emp_cond = f"employee_id = '{emp}'"
        att_cond = f"employee_id = '{emp}'"
        leave_cond = f"employee_id = '{emp}'"
        anom_cond = f"scope_type = 'employee' AND employee_id = '{emp}'"

    conn.execute(f"CREATE TEMP VIEW v_employees AS SELECT * FROM main.v_employees WHERE {emp_cond}")
    conn.execute(f"CREATE TEMP VIEW v_attendance_daily AS SELECT * FROM main.v_attendance_daily WHERE {att_cond}")
    conn.execute(f"CREATE TEMP VIEW v_leave_requests AS SELECT * FROM main.v_leave_requests WHERE {leave_cond}")
    conn.execute(f"CREATE TEMP VIEW v_anomalies AS SELECT * FROM main.v_anomalies WHERE {anom_cond}")


def execute_guarded_sql(
    db_path: Optional[Path | str],
    user: AuthenticatedUser,
    sql: str,
    params: Optional[Dict[str, Any] | List[Any]] = None,
    max_rows: Optional[int] = None,
    timeout_seconds: Optional[float] = None,
) -> Tuple[List[Dict[str, Any]], str, float]:
    """Validate and execute read-only SQL on RBAC-scoped TEMP views with SQLite authorizer & timeout guard."""
    limit = max_rows or settings.ai_query_max_rows
    timeout = timeout_seconds or float(settings.ai_query_timeout_seconds)
    validated_sql = validate_readonly_sql(sql, max_rows=limit)

    conn = get_connection(db_path=db_path, readonly=True)
    start_ts = time.monotonic()
    try:
        _create_scoped_temp_views(conn, user)

        # Install SQLite authorizer blocking any write or access to sensitive tables
        forbidden_base_tables = {
            "users", "activity_logs", "query_audit_log", "import_logs",
            "leave_approval_logs", "sqlite_master", "sqlite_schema", "sqlite_temp_master",
        }

        def authorizer(action_code, arg1, arg2, db_name, trigger_name):
            if action_code == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            if action_code == sqlite3.SQLITE_FUNCTION:
                return sqlite3.SQLITE_OK
            if action_code == sqlite3.SQLITE_READ:
                tbl = (arg1 or "").lower()
                col = (arg2 or "").lower()
                if tbl in forbidden_base_tables or col == "password_hash":
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        def progress_handler():
            if (time.monotonic() - start_ts) > timeout:
                return 1  # Interrupt query
            return 0

        conn.set_authorizer(authorizer)
        conn.set_progress_handler(progress_handler, 1000)

        cursor = conn.execute(validated_sql, params or [])
        rows = [dict(r) for r in cursor.fetchmany(limit)]
        elapsed_ms = round((time.monotonic() - start_ts) * 1000.0, 2)
        return rows, validated_sql, elapsed_ms
    except sqlite3.OperationalError as exc:
        msg = str(exc).lower()
        if "interrupted" in msg:
            raise SQLGuardError(f"Truy vấn vượt quá giới hạn thời gian ({timeout} giây).")
        if "not authorized" in msg:
            raise SQLGuardError("Truy vấn bị chặn bởi lớp bảo mật SQLite Authorizer.")
        raise SQLGuardError(f"Lỗi thực thi truy vấn đọc: {exc}")
    except sqlite3.DatabaseError as exc:
        raise SQLGuardError(f"Truy vấn không hợp lệ hoặc bị chặn: {exc}")
    finally:
        conn.close()
