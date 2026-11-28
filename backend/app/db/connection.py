from __future__ import annotations

import datetime
from decimal import Decimal
from pathlib import Path
import re
import sqlite3
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from app.core.config import settings

try:
    import psycopg
    from psycopg import pq as _pg_pq
except ImportError:  # pragma: no cover - optional when running SQLite-only
    psycopg = None  # type: ignore[assignment]
    _pg_pq = None  # type: ignore[assignment]

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
SCHEMA_POSTGRES_PATH = Path(__file__).resolve().parent / "schema_postgres.sql"
DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "hr_attendance.db"

DB_INTEGRITY_ERRORS: Tuple[type[BaseException], ...] = (
    (sqlite3.IntegrityError, psycopg.IntegrityError) if psycopg is not None else (sqlite3.IntegrityError,)
)

_AUTO_PK_BY_TABLE: Dict[str, str] = {
    "leave_requests": "request_id",
    "import_logs": "id",
    "attendance": "id",
    "anomalies": "anomaly_id",
    "leave_approval_logs": "id",
    "activity_logs": "id",
    "query_audit_log": "id",
    "overtime_requests": "id",
    "notifications": "notification_id",
    "face_consent_records": "consent_id",
    "face_scan_logs": "id",
    "roles": "role_id",
    "permissions": "permission_id",
    "company_documents": "document_id",
    "document_chunks": "chunk_id",
}


def is_postgres_url(url: Optional[str] = None) -> bool:
    raw = (url if url is not None else settings.database_url) or ""
    return raw.strip().lower().startswith(("postgresql://", "postgres://"))


def is_postgres_connection(conn: Any) -> bool:
    return isinstance(conn, PostgresCompatConnection)


def _normalize_pg_value(val: Any) -> Any:
    if isinstance(val, datetime.datetime):
        return val.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(val, datetime.date):
        return val.isoformat()
    if isinstance(val, Decimal):
        return float(val)
    return val


class CompatRow:
    """Drop-in sqlite3.Row compatible row supporting both row['col'] and row[0] plus dict(row)."""

    __slots__ = ("_keys", "_values", "_map")

    def __init__(self, columns: Sequence[str], raw_values: Sequence[Any]) -> None:
        self._keys = tuple(columns)
        self._values = tuple(_normalize_pg_value(v) for v in raw_values)
        self._map = dict(zip(self._keys, self._values))

    def keys(self) -> Tuple[str, ...]:
        return self._keys

    def get(self, key: str, default: Any = None) -> Any:
        return self._map.get(key, default)

    def __getitem__(self, key: Union[str, int, slice]) -> Any:
        if isinstance(key, (int, slice)):
            return self._values[key]
        return self._map[key]

    def __contains__(self, key: object) -> bool:
        return key in self._map

    def __len__(self) -> int:
        return len(self._keys)

    def __iter__(self):
        return iter(self._keys)

    def __repr__(self) -> str:
        return f"CompatRow({self._map!r})"


def translate_sqlite_sql_for_postgres(sql: str) -> str:
    """Translate SQLite-style placeholders (?, :name) and ASCII LIKE to PostgreSQL syntax safely.

    Preserves single-quoted string literals and PostgreSQL typecasts (::numeric, ::jsonb, etc.).
    """
    out: List[str] = []
    i = 0
    n = len(sql)
    in_single_quote = False

    while i < n:
        ch = sql[i]
        if in_single_quote:
            out.append(ch)
            if ch == "'":
                if i + 1 < n and sql[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                in_single_quote = False
            i += 1
            continue

        if ch == "'":
            in_single_quote = True
            out.append(ch)
            i += 1
            continue

        if ch == "?":
            out.append("%s")
            i += 1
            continue

        # Named placeholder :param_name (skip PostgreSQL ::type cast!)
        if ch == ":":
            prev_ch = sql[i - 1] if i > 0 else ""
            next_ch = sql[i + 1] if i + 1 < n else ""
            if prev_ch != ":" and next_ch != ":" and (next_ch.isalpha() or next_ch == "_"):
                j = i + 1
                while j < n and (sql[j].isalnum() or sql[j] == "_"):
                    j += 1
                name = sql[i + 1 : j]
                out.append(f"%({name})s")
                i = j
                continue
            out.append(ch)
            i += 1
            continue

        # Translate standalone LIKE -> ILIKE so searches remain case-insensitive like SQLite
        if (ch in ("L", "l")) and i + 4 <= n and sql[i : i + 4].upper() == "LIKE":
            prev_ok = i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_")
            next_ok = i + 4 == n or not (sql[i + 4].isalnum() or sql[i + 4] == "_")
            if prev_ok and next_ok:
                out.append("ILIKE")
                i += 4
                continue

        out.append(ch)
        i += 1

    return "".join(out)


class CompatCursor:
    """sqlite3.Cursor-compatible wrapper around a psycopg cursor."""

    def __init__(self, pg_cursor: Any = None, auto_lastrowid: Optional[int] = None) -> None:
        self._cur = pg_cursor
        self.lastrowid: Optional[int] = auto_lastrowid
        self.rowcount: int = pg_cursor.rowcount if pg_cursor is not None else 0
        self._columns: Tuple[str, ...] = (
            tuple(col.name for col in pg_cursor.description)
            if (pg_cursor is not None and pg_cursor.description)
            else ()
        )

    def _wrap(self, row: Any) -> Optional[CompatRow]:
        if row is None:
            return None
        return CompatRow(self._columns, row)

    def fetchone(self) -> Optional[CompatRow]:
        if self._cur is None:
            return None
        return self._wrap(self._cur.fetchone())

    def fetchall(self) -> List[CompatRow]:
        if self._cur is None:
            return []
        return [CompatRow(self._columns, r) for r in self._cur.fetchall()]

    def fetchmany(self, size: int = 1) -> List[CompatRow]:
        if self._cur is None:
            return []
        return [CompatRow(self._columns, r) for r in self._cur.fetchmany(size)]

    def close(self) -> None:
        if self._cur is not None:
            self._cur.close()


class PostgresCompatConnection:
    """sqlite3.Connection-compatible adapter over psycopg3 for seamless Supabase PostgreSQL support."""

    def __init__(self, pg_conn: Any) -> None:
        self._conn = pg_conn

    @property
    def raw_connection(self) -> Any:
        return self._conn

    def execute(self, sql: str, params: Any = None) -> CompatCursor:
        stripped = sql.strip()
        upper = stripped.upper()

        # Handle explicit SQLite transaction control smoothly on psycopg
        if upper in ("BEGIN", "BEGIN IMMEDIATE", "BEGIN TRANSACTION"):
            if _pg_pq is not None and self._conn.info.transaction_status == _pg_pq.TransactionStatus.INTRANS:
                return CompatCursor(None)
            cur = self._conn.cursor()
            cur.execute("BEGIN")
            return CompatCursor(cur)

        if upper.startswith("PRAGMA "):
            return CompatCursor(None)

        pg_sql = translate_sqlite_sql_for_postgres(sql)

        # Auto-append RETURNING <pk> for INSERTs expecting cursor.lastrowid
        auto_returning = False
        if upper.startswith("INSERT INTO ") and "RETURNING " not in upper:
            m = re.match(r"^\s*INSERT\s+INTO\s+(?:public\.)?([a-zA-Z_][a-zA-Z0-9_]*)", pg_sql, flags=re.IGNORECASE)
            if m:
                tbl = m.group(1).lower()
                pk_col = _AUTO_PK_BY_TABLE.get(tbl)
                if pk_col:
                    pg_sql = pg_sql.rstrip().rstrip(";") + f" RETURNING {pk_col}"
                    auto_returning = True

        cur = self._conn.cursor()
        if params is None:
            cur.execute(pg_sql)
        elif isinstance(params, dict):
            cur.execute(pg_sql, params)
        elif isinstance(params, (list, tuple)):
            cur.execute(pg_sql, tuple(params))
        else:
            cur.execute(pg_sql, params)

        lastrowid = None
        if auto_returning and cur.description:
            row = cur.fetchone()
            if row:
                lastrowid = int(row[0])
            return CompatCursor(None, auto_lastrowid=lastrowid)

        return CompatCursor(cur)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def resolve_db_path(db_path: Optional[Path | str] = None) -> Path:
    if db_path is not None:
        return Path(db_path).resolve()
    url = settings.database_url
    if url.startswith("sqlite:///"):
        raw = url.replace("sqlite:///", "", 1)
        p = Path(raw)
        if not p.is_absolute():
            return (Path(__file__).resolve().parents[2] / p).resolve()
        return p.resolve()
    return DEFAULT_DB_PATH


def get_connection(
    db_path: Optional[Path | str] = None,
    readonly: bool = False,
) -> Union[sqlite3.Connection, PostgresCompatConnection]:
    # Explicit db_path always opens local SQLite (used by isolated pytest suites & local tooling)
    if db_path is None and is_postgres_url(settings.database_url):
        if psycopg is None:
            raise RuntimeError("Thiếu thư viện psycopg. Hãy chạy: pip install 'psycopg[binary]>=3.2.0'")
        pg_conn = psycopg.connect(settings.database_url, autocommit=False)
        if readonly:
            pg_conn.read_only = True
        return PostgresCompatConnection(pg_conn)

    path = resolve_db_path(db_path)
    if readonly:
        uri = f"file:{path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Optional[Path | str] = None) -> Path:
    path = resolve_db_path(db_path)
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = get_connection(path, readonly=False)
    try:
        conn.executescript(schema_sql)
        conn.commit()
    finally:
        conn.close()
    return path
