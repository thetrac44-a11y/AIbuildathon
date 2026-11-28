from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import sqlglot
from sqlglot import exp

from app.core.config import settings
from app.core.security import AuthenticatedUser, resolve_ai_effective_scope
from app.db.connection import get_connection, is_postgres_connection

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
        "requires_executive_approval", "reviewed_by", "reviewed_at", "decision_note", "created_at",
    },
    "v_anomalies": {
        "anomaly_id", "employee_id", "full_name", "department_id", "department_name",
        "scope_type", "rule_code", "anomaly_type", "severity", "period", "evidence",
        "explanation", "review_status", "reviewed_by", "reviewed_at", "review_note", "detected_at",
    },
}

ALL_ALLOWED_COLUMNS: Set[str] = set().union(*ALLOWED_VIEW_COLUMNS.values())

FORBIDDEN_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "create", "replace",
    "attach", "detach", "pragma", "vacuum", "reindex", "load_extension",
    "truncate", "grant", "revoke", "commit", "rollback", "begin", "savepoint",
    "exec", "execute", "copy", "merge", "call", "do", "into",
}

FORBIDDEN_IDENTIFIERS = {
    # Sensitive / system / audit tables (SQLite + PostgreSQL)
    "users", "password_hash", "sqlite_master", "sqlite_schema", "sqlite_temp_master",
    "sqlite_sequence", "activity_logs", "query_audit_log", "import_logs",
    "leave_approval_logs", "main", "temp", "public",
    "pg_catalog", "pg_tables", "pg_class", "pg_roles", "pg_user", "pg_shadow",
    "pg_authid", "information_schema",
    # Raw base tables (must NEVER be queried directly; only the 4 RBAC-scoped v_* TEMP views are allowed)
    "employees", "attendance", "leave_requests", "anomalies",
    "departments", "holidays", "overtime_requests", "positions",
    "roles", "permissions", "user_roles", "role_permissions",
    "attendance_policies", "notifications", "kiosk_devices",
    "face_profiles", "face_consent_records", "face_scan_logs",
    "company_documents", "document_chunks", "system_settings", "revoked_tokens",
    # Sensitive employee PII excluded from v_employees
    "email", "phone", "embedding_ciphertext", "device_secret_hash",
}

FORBIDDEN_SQL_FUNCTIONS = {
    "pg_sleep", "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file",
    "pg_backend_pid", "pg_terminate_backend", "pg_cancel_backend", "pg_reload_conf",
    "pg_rotate_logfile", "pg_current_logfile", "pg_export_snapshot",
    "current_setting", "set_config", "version", "current_user", "session_user",
    "current_database", "current_schema", "current_schemas",
    "inet_server_addr", "inet_server_port", "inet_client_addr", "inet_client_port",
    "dblink", "dblink_exec", "dblink_connect", "dblink_open",
    "lo_import", "lo_export", "lo_get", "lo_put", "lo_unlink",
    "query_to_xml", "table_to_xml", "database_to_xml",
    "load_extension", "sqlite_version", "sqlite_source_id", "randomblob", "zeroblob",
    "txid_current", "pg_advisory_lock", "pg_try_advisory_lock",
}

FORBIDDEN_FUNCTION_PREFIXES = ("pg_", "lo_", "dblink", "sqlite_", "brin_", "gin_", "gist_")

ALLOWED_SQL_FUNCTIONS = {
    # Aggregates
    "count", "sum", "avg", "min", "max", "group_concat", "string_agg", "array_agg",
    # Math & numeric
    "round", "abs", "floor", "ceil", "ceiling", "greatest", "least",
    # Null handling & conditionals
    "coalesce", "nullif", "ifnull", "iif", "case", "if",
    # String safe operations
    "lower", "upper", "trim", "ltrim", "rtrim", "length", "char_length",
    "substr", "substring", "replace", "concat", "left", "right",
    # Type & date safe operations
    "cast", "to_char", "date", "strftime", "extract", "date_part", "date_trunc", "julianday",
    "current_date",
}

FORBIDDEN_AST_NODE_TYPES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Command,
    exp.Copy,
    exp.Merge,
    exp.Into,
    exp.Lock,
    exp.Pragma,
    exp.Set,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Grant,
    exp.Revoke,
)

HARD_MAX_ROWS_CEILING = 500
HARD_TIMEOUT_CEILING_SECONDS = 10.0


class SQLGuardError(ValueError):
    """Raised whenever a SQL query violates security or allowlist policy."""


def _parse_sql_ast(cleaned_sql: str) -> exp.Expression:
    """Parse SQL into a single sqlglot AST tree (tries PostgreSQL dialect first, then SQLite)."""
    last_error: Optional[Exception] = None
    for dialect in ("postgres", "sqlite"):
        try:
            statements = sqlglot.parse(cleaned_sql, read=dialect)
            if not statements or len(statements) != 1 or statements[0] is None:
                raise SQLGuardError("Chỉ cho phép đúng một câu lệnh SQL đọc hợp lệ.")
            return statements[0]
        except SQLGuardError:
            raise
        except Exception as exc:
            last_error = exc
    raise SQLGuardError(f"Không thể phân tích cú pháp SQL (AST Guard): {last_error}")


def _extract_func_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return (node.name or "").strip().lower()
    sql_name = node.sql_name() if hasattr(node, "sql_name") else ""
    if sql_name:
        return sql_name.strip().lower()
    return node.key.lower()


def _validate_ast(tree: exp.Expression) -> None:
    """Enforce strict AST-level SELECT-only, view allowlist, column allowlist, and safe function policy."""
    if not isinstance(tree, (exp.Select, exp.Union)):
        raise SQLGuardError("Chỉ cho phép câu lệnh truy vấn đọc SELECT / WITH ... SELECT.")

    # 1. Reject any DDL/DML/Locking/Command node anywhere in the AST
    for node in tree.walk():
        if isinstance(node, FORBIDDEN_AST_NODE_TYPES):
            raise SQLGuardError(f"Biểu thức SQL không được phép trong chế độ chỉ đọc: {type(node).__name__}.")

    # 2. Collect CTE definitions and their declared output aliases
    cte_names: Set[str] = set()
    cte_columns: Dict[str, Set[str]] = {}
    for cte in tree.find_all(exp.CTE):
        cname = (cte.alias_or_name or "").strip().lower()
        if not cname:
            continue
        if cname in FORBIDDEN_IDENTIFIERS:
            raise SQLGuardError(f"Tên CTE không được phép trùng định danh hệ thống: {cname}.")
        cte_names.add(cname)
        cols: Set[str] = set()
        cte_query = cte.this
        if isinstance(cte_query, (exp.Select, exp.Union)):
            select_node = cte_query if isinstance(cte_query, exp.Select) else cte_query.this
            if isinstance(select_node, exp.Select):
                for proj in select_node.expressions:
                    if isinstance(proj, exp.Star):
                        cols.update(ALL_ALLOWED_COLUMNS)
                    elif isinstance(proj, exp.Alias) and proj.alias:
                        cols.add(proj.alias.lower())
                    elif isinstance(proj, exp.Column) and proj.name:
                        cols.add(proj.name.lower())
        cte_columns[cname] = cols or set(ALL_ALLOWED_COLUMNS)

    # 3. Validate EVERY referenced table/view & build alias -> target map
    referenced_real_views: Set[str] = set()
    table_alias_map: Dict[str, str] = {}
    for tbl in tree.find_all(exp.Table):
        if tbl.db or tbl.catalog:
            qualified = ".".join(p for p in (tbl.catalog, tbl.db, tbl.name) if p)
            raise SQLGuardError(f"Không cho phép truy cập trực tiếp schema/prefix: {qualified}.")
        tname = (tbl.name or "").strip().lower()
        if not tname:
            raise SQLGuardError("Tên bảng/view truy vấn không hợp lệ.")
        if tname in ALLOWED_VIEWS:
            referenced_real_views.add(tname)
        elif tname not in cte_names:
            raise SQLGuardError(f"Bảng/view '{tbl.name}' không nằm trong allowlist an toàn cho AI.")

        table_alias_map[tname] = tname
        if tbl.alias:
            alias_l = tbl.alias.strip().lower()
            if alias_l in FORBIDDEN_IDENTIFIERS:
                raise SQLGuardError(f"Bí danh bảng không được phép: {alias_l}.")
            table_alias_map[alias_l] = tname

    if not referenced_real_views:
        raise SQLGuardError("Truy vấn phải tham chiếu ít nhất một view hợp lệ trong allowlist.")

    # 4. Validate EVERY function call (block PG/SQLite system functions & enforce safe function allowlist)
    for fn in tree.find_all(exp.Func):
        # In sqlglot v30+, logical/comparison operators (And/Or/Xor/Binary/Unary) may inherit from Func;
        # skip pure SQL operators (never skipping exp.Anonymous or real SQL functions).
        if isinstance(fn, (exp.Connector, exp.Binary, exp.Unary)) and not isinstance(fn, exp.Anonymous):
            continue
        fname = _extract_func_name(fn)
        if not fname:
            continue
        if fname in FORBIDDEN_SQL_FUNCTIONS or fname.startswith(FORBIDDEN_FUNCTION_PREFIXES):
            raise SQLGuardError(f"Hàm SQL hệ thống bị chặn bởi SQL Guard: {fname}().")
        if fname not in ALLOWED_SQL_FUNCTIONS:
            raise SQLGuardError(f"Hàm SQL '{fname}()' không nằm trong danh sách hàm đọc an toàn được phép.")

    # Also catch zero-arg SQL keywords parsed as special nodes (e.g. CURRENT_USER, SESSION_USER)
    for node in tree.walk():
        if isinstance(node, (exp.CurrentUser, exp.SessionUser, exp.CurrentSchema, exp.CurrentCatalog)):
            raise SQLGuardError(f"Biểu thức thông tin hệ thống không được phép: {type(node).__name__}.")

    # 5. Collect output aliases declared via AS <alias> (used in ORDER BY / GROUP BY / HAVING)
    declared_output_aliases: Set[str] = set()
    for alias_node in tree.find_all(exp.Alias):
        if alias_node.alias:
            a_l = alias_node.alias.strip().lower()
            if a_l in FORBIDDEN_IDENTIFIERS:
                raise SQLGuardError(f"Bí danh cột không được phép: {a_l}.")
            declared_output_aliases.add(a_l)

    # Compute allowed unqualified columns from all referenced real views + CTEs
    allowed_unqualified_cols: Set[str] = set(declared_output_aliases)
    for vname in referenced_real_views:
        allowed_unqualified_cols.update(ALLOWED_VIEW_COLUMNS[vname])
    for cname in cte_names:
        allowed_unqualified_cols.update(cte_columns.get(cname, set()))

    # 6. Validate EVERY explicit column against ALLOWED_VIEW_COLUMNS
    for col in tree.find_all(exp.Column):
        if isinstance(col.this, exp.Star):
            continue
        col_name = (col.name or "").strip().lower()
        if not col_name:
            continue
        if col_name in FORBIDDEN_IDENTIFIERS:
            raise SQLGuardError(f"Cột dữ liệu nhạy cảm không được phép truy vấn: {col_name}.")
        if col.db or col.catalog:
            raise SQLGuardError(f"Không cho phép tham chiếu cột theo schema: {col.sql()}.")

        tbl_ref = (col.table or "").strip().lower()
        if tbl_ref:
            target = table_alias_map.get(tbl_ref)
            if not target:
                raise SQLGuardError(f"Tiền tố bảng/alias '{tbl_ref}' không khớp bất kỳ view hợp lệ nào.")
            if target in ALLOWED_VIEWS:
                if col_name not in ALLOWED_VIEW_COLUMNS[target]:
                    raise SQLGuardError(
                        f"Cột '{col_name}' không nằm trong danh sách cột được phép của view '{target}'."
                    )
            elif target in cte_names:
                if col_name not in cte_columns.get(target, set()):
                    raise SQLGuardError(
                        f"Cột '{col_name}' không nằm trong danh sách cột được phép của CTE '{target}'."
                    )
        else:
            if col_name not in allowed_unqualified_cols:
                raise SQLGuardError(
                    f"Cột '{col_name}' không nằm trong danh sách cột được phép của các view đã tham chiếu."
                )


def validate_readonly_sql(sql: str, max_rows: int = 200) -> str:
    """Strictly validate SQL text: AST SELECT-only on allowlisted views/columns, safe functions, enforce LIMIT."""
    if not sql or not sql.strip():
        raise SQLGuardError("Câu lệnh SQL rỗng.")

    effective_max_rows = max(1, min(int(max_rows), HARD_MAX_ROWS_CEILING))
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

    # Block quoted/bracketed identifiers ("...", `...`, [...]) that could evade checks
    if any(ch in no_strings for ch in ('"', "`", "[", "]")):
        raise SQLGuardError("Không cho phép dùng định danh bọc dấu ngoặc (\", `, [ ]). Chỉ truy vấn trực tiếp 4 view hợp lệ.")

    # Block comma-separated FROM joins (e.g. FROM v_employees, employees)
    if re.search(r"\bfrom\s+[a-zA-Z_][a-zA-Z0-9_]*(?:\s+(?:as\s+)?[a-zA-Z_][a-zA-Z0-9_]*)?\s*,", no_strings, flags=re.IGNORECASE):
        raise SQLGuardError("Không cho phép cú pháp comma-join trong FROM. Hãy dùng JOIN tường minh giữa các view hợp lệ.")

    # Defense-in-depth lexical scan
    tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", no_strings)
    lower_tokens = [t.lower() for t in tokens]

    for kw in FORBIDDEN_KEYWORDS:
        if kw in lower_tokens:
            raise SQLGuardError(f"Từ khóa SQL không được phép: {kw.upper()}.")

    for ident in FORBIDDEN_IDENTIFIERS:
        if ident in lower_tokens:
            raise SQLGuardError(f"Đối tượng hoặc cột dữ liệu không nằm trong danh sách cho phép: {ident}.")

    # Full AST validation (views, columns, functions, subqueries, CTEs)
    tree = _parse_sql_ast(cleaned)
    _validate_ast(tree)

    # Enforce outer row limit <= effective_max_rows (match strictly at the end of the outer query)
    limit_match = re.search(r"\blimit\s+(\d+)(?:\s+offset\s+\d+)?\s*$", no_strings, flags=re.IGNORECASE)
    if limit_match:
        requested_limit = int(limit_match.group(1))
        if requested_limit > effective_max_rows:
            cleaned = re.sub(
                r"\blimit\s+\d+(\s+offset\s+\d+)?\s*$",
                lambda m: f"LIMIT {effective_max_rows}{m.group(1) or ''}",
                cleaned,
                count=1,
                flags=re.IGNORECASE,
            )
    else:
        cleaned = f"{cleaned} LIMIT {effective_max_rows}"

    return cleaned


def _resolve_runtime_guard_limits(
    conn: Any,
    max_rows: Optional[int] = None,
    timeout_seconds: Optional[float] = None,
) -> Tuple[int, float]:
    """Read dynamic ai.sql_max_rows & ai.sql_timeout_seconds from system_settings within hard ceilings."""
    resolved_rows = settings.ai_query_max_rows
    resolved_timeout = float(settings.ai_query_timeout_seconds)

    if max_rows is None or timeout_seconds is None:
        try:
            rows = conn.execute(
                "SELECT setting_key, setting_value FROM system_settings WHERE setting_key IN ('ai.sql_max_rows', 'ai.sql_timeout_seconds')"
            ).fetchall()
            for r in rows:
                k = r["setting_key"]
                v = str(r["setting_value"]).strip()
                if k == "ai.sql_max_rows" and v.isdigit():
                    resolved_rows = int(v)
                elif k == "ai.sql_timeout_seconds":
                    try:
                        resolved_timeout = float(v)
                    except ValueError:
                        pass
        except Exception:
            if is_postgres_connection(conn):
                try:
                    conn.rollback()
                except Exception:
                    pass

    final_rows = max(1, min(int(max_rows if max_rows is not None else resolved_rows), HARD_MAX_ROWS_CEILING))
    final_timeout = max(0.5, min(float(timeout_seconds if timeout_seconds is not None else resolved_timeout), HARD_TIMEOUT_CEILING_SECONDS))
    return final_rows, final_timeout


def _create_scoped_temp_views(conn: Any, user: AuthenticatedUser) -> None:
    """Create TEMP views shadowing the 4 allowlisted views with authoritative EffectiveScopeResolver scope."""
    scope = resolve_ai_effective_scope(user)
    if scope == "none":
        raise SQLGuardError(
            "Vai trò hoặc quyền hiện tại không được phép truy vấn SQL dữ liệu nghiệp vụ nhân sự."
        )
    if scope == "all":
        emp_cond = "1 = 1"
        att_cond = "1 = 1"
        leave_cond = "1 = 1"
        anom_cond = "1 = 1"
    elif scope == "department":
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

    source_schema = "public" if is_postgres_connection(conn) else "main"
    # Project ONLY the canonical allowlisted columns so SQLite & PostgreSQL views expose identical safe columns
    emp_cols = ", ".join(sorted(ALLOWED_VIEW_COLUMNS["v_employees"]))
    att_cols = ", ".join(sorted(ALLOWED_VIEW_COLUMNS["v_attendance_daily"]))
    lv_cols = ", ".join(sorted(ALLOWED_VIEW_COLUMNS["v_leave_requests"]))
    an_cols = ", ".join(sorted(ALLOWED_VIEW_COLUMNS["v_anomalies"]))

    conn.execute(f"CREATE TEMP VIEW v_employees AS SELECT {emp_cols} FROM {source_schema}.v_employees WHERE {emp_cond}")
    conn.execute(f"CREATE TEMP VIEW v_attendance_daily AS SELECT {att_cols} FROM {source_schema}.v_attendance_daily WHERE {att_cond}")
    conn.execute(f"CREATE TEMP VIEW v_leave_requests AS SELECT {lv_cols} FROM {source_schema}.v_leave_requests WHERE {leave_cond}")
    conn.execute(f"CREATE TEMP VIEW v_anomalies AS SELECT {an_cols} FROM {source_schema}.v_anomalies WHERE {anom_cond}")


def execute_guarded_sql(
    db_path: Optional[Path | str],
    user: AuthenticatedUser,
    sql: str,
    params: Optional[Dict[str, Any] | List[Any]] = None,
    max_rows: Optional[int] = None,
    timeout_seconds: Optional[float] = None,
) -> Tuple[List[Dict[str, Any]], str, float]:
    """Validate (AST + Allowlist) and execute read-only SQL on RBAC-scoped TEMP views (SQLite & Supabase PostgreSQL)."""
    if resolve_ai_effective_scope(user) == "none":
        raise SQLGuardError(
            "Vai trò hoặc quyền hiện tại không được phép truy vấn SQL dữ liệu nghiệp vụ nhân sự."
        )

    # First-pass AST validation before opening any DB connection
    pre_limit = max_rows or settings.ai_query_max_rows
    validate_readonly_sql(sql, max_rows=pre_limit)

    conn = get_connection(db_path=db_path, readonly=False if db_path is None else True)
    start_ts = time.monotonic()
    try:
        limit, timeout = _resolve_runtime_guard_limits(conn, max_rows=max_rows, timeout_seconds=timeout_seconds)
        validated_sql = validate_readonly_sql(sql, max_rows=limit)

        if is_postgres_connection(conn):
            _create_scoped_temp_views(conn, user)
            conn.commit()
            try:
                conn.execute("BEGIN TRANSACTION READ ONLY")
                conn.execute(f"SET LOCAL statement_timeout = {max(500, int(timeout * 1000))}")
                cursor = conn.execute(validated_sql, params or [])
                rows = [dict(r) for r in cursor.fetchmany(limit)]
                elapsed_ms = round((time.monotonic() - start_ts) * 1000.0, 2)
                return rows, validated_sql, elapsed_ms
            except Exception as exc:
                msg = str(exc).lower()
                if "statement timeout" in msg or "canceling statement" in msg:
                    raise SQLGuardError(f"Truy vấn vượt quá giới hạn thời gian ({timeout} giây).")
                if "read-only transaction" in msg:
                    raise SQLGuardError("Truy vấn ghi bị chặn bởi giao dịch READ ONLY của PostgreSQL.")
                raise SQLGuardError(f"Lỗi thực thi truy vấn đọc PostgreSQL: {exc}")
            finally:
                try:
                    conn.rollback()
                except Exception:
                    pass

        # SQLite path: re-open strict mode=ro if opened read-write above
        if db_path is None:
            conn.close()
            conn = get_connection(db_path=None, readonly=True)

        _create_scoped_temp_views(conn, user)

        # Install SQLite authorizer blocking any write or access to sensitive tables / dangerous functions
        forbidden_base_tables = {
            "users", "activity_logs", "query_audit_log", "import_logs",
            "leave_approval_logs", "system_settings", "revoked_tokens", "roles", "permissions",
            "user_roles", "role_permissions", "kiosk_devices",
            "sqlite_master", "sqlite_schema", "sqlite_temp_master",
        }

        def authorizer(action_code, arg1, arg2, db_name, trigger_name):
            if action_code == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            if action_code == sqlite3.SQLITE_FUNCTION:
                fn_name = (arg2 or "").lower()
                if fn_name in FORBIDDEN_SQL_FUNCTIONS or fn_name.startswith(FORBIDDEN_FUNCTION_PREFIXES):
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            if action_code == sqlite3.SQLITE_READ:
                tbl = (arg1 or "").lower()
                col = (arg2 or "").lower()
                if tbl in forbidden_base_tables or col in ("password_hash", "email", "phone", "embedding_ciphertext"):
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
