from pathlib import Path
import sqlite3
from typing import Optional
from app.core.config import settings

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "hr_attendance.db"


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


def get_connection(db_path: Optional[Path | str] = None, readonly: bool = False) -> sqlite3.Connection:
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
