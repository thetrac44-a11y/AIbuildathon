import datetime
from decimal import Decimal
from pathlib import Path
import pytest

from app.db.connection import (
    CompatRow,
    is_postgres_url,
    translate_sqlite_sql_for_postgres,
)
from app.services.anomaly_service import RULE_SQL_FILES, SQL_PG_DIR
from app.services.sql_guard import SQLGuardError, validate_readonly_sql


def test_postgres_url_detection():
    assert is_postgres_url("postgresql://postgres:secret@host:5432/postgres") is True
    assert is_postgres_url("postgres://user:pass@host/db") is True
    assert is_postgres_url("sqlite:///./hr_attendance.db") is False


def test_sql_translation_preserves_string_literals_and_pg_typecasts():
    sql = (
        "SELECT employee_id, ROUND((work_hours)::numeric, 2) "
        "FROM v_attendance_daily "
        "WHERE employee_id = ? "
        "AND full_name LIKE ? "
        "AND note <> 'what? :not_a_param like this' "
        "AND (CAST(:period AS TEXT) IS NULL OR period = :period)"
    )
    translated = translate_sqlite_sql_for_postgres(sql)
    assert "ROUND((work_hours)::numeric, 2)" in translated
    assert "employee_id = %s" in translated
    assert "full_name ILIKE %s" in translated
    assert "'what? :not_a_param like this'" in translated
    assert "CAST(%(period)s AS TEXT) IS NULL OR period = %(period)s" in translated


def test_compat_row_supports_dict_and_positional_access_with_type_normalization():
    row = CompatRow(
        ["employee_id", "work_date", "check_in", "work_hours", "evidence"],
        [
            "NV007",
            datetime.date(2026, 10, 2),
            datetime.datetime(2026, 10, 2, 8, 48, 17),
            Decimal("7.86"),
            {"late_days": 8},
        ],
    )
    assert row["employee_id"] == "NV007"
    assert row[0] == "NV007"
    assert row["work_date"] == "2026-10-02"
    assert row["check_in"] == "2026-10-02 08:48:17"
    assert row["work_hours"] == 7.86
    assert isinstance(row["work_hours"], float)
    assert row["evidence"] == {"late_days": 8}
    assert dict(row)["work_hours"] == 7.86


def test_all_eight_postgres_anomaly_rules_present_and_sqlite_free():
    for rule_code, _, filename in RULE_SQL_FILES:
        pg_file = Path(SQL_PG_DIR) / filename
        assert pg_file.exists(), f"Missing PostgreSQL rule file: {pg_file}"
        sql_text = pg_file.read_text(encoding="utf-8")
        assert "GROUP_CONCAT" not in sql_text.upper(), f"{rule_code} still contains GROUP_CONCAT"
        assert "JULIANDAY" not in sql_text.upper(), f"{rule_code} still contains julianday"
        assert "CAST(:period AS TEXT) IS NULL" in sql_text, f"{rule_code} missing typed period NULL guard"
        translated = translate_sqlite_sql_for_postgres(sql_text)
        assert "%(period)s" in translated
        assert "::TEXT" in translated or "::numeric" in translated


def test_sql_guard_blocks_postgres_system_catalogs_and_biometric_tables():
    dangerous_pg_queries = [
        "SELECT * FROM pg_catalog.pg_tables",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM pg_roles",
        "SELECT * FROM face_profiles",
        "SELECT embedding_ciphertext FROM v_employees",
        "SELECT * FROM public.v_employees",
    ]
    for q in dangerous_pg_queries:
        with pytest.raises(SQLGuardError):
            validate_readonly_sql(q)
