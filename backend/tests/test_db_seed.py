import sqlite3
import bcrypt
import pytest
from app.db.connection import get_connection
from app.db.seed import DEV_DEFAULT_PASSWORD, seed_database


@pytest.fixture()
def seeded_db(tmp_path):
    db_file = tmp_path / "test_hr.db"
    summary = seed_database(db_path=db_file, reset=True)
    return db_file, summary


def test_schema_tables_views_and_seed_counts(seeded_db):
    db_file, summary = seeded_db
    assert summary["departments"] == 5
    assert summary["employees"] == 80
    assert summary["users"] == 80
    assert summary["attendance"] > 9000
    assert summary["leave_requests"] >= 10

    conn = get_connection(db_file)
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        expected_tables = {
            "departments",
            "employees",
            "attendance",
            "leave_requests",
            "holidays",
            "anomalies",
            "query_audit_log",
            "users",
            "leave_approval_logs",
            "import_logs",
            "activity_logs",
            "overtime_requests",
        }
        assert expected_tables.issubset(tables)

        views = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchall()
        }
        assert {"v_employees", "v_attendance_daily", "v_leave_requests", "v_anomalies"}.issubset(views)

        # Verify date range 2026-06-01 to 2026-11-30
        row = conn.execute("SELECT MIN(work_date), MAX(work_date) FROM attendance").fetchone()
        assert row[0] == "2026-06-01"
        assert row[1] == "2026-11-30"

        # Verify passwords are bcrypt hashed (never plaintext)
        user_row = conn.execute("SELECT password_hash FROM users WHERE username = 'hr@company.vn'").fetchone()
        assert user_row is not None
        assert user_row[0] != DEV_DEFAULT_PASSWORD
        assert user_row[0].startswith("$2")
        assert bcrypt.checkpw(DEV_DEFAULT_PASSWORD.encode("utf-8"), user_row[0].encode("utf-8"))
    finally:
        conn.close()


def test_seed_is_idempotent(seeded_db):
    db_file, first_summary = seeded_db
    second_summary = seed_database(db_path=db_file, reset=False)
    assert second_summary["skipped_existing"] == 1
    assert second_summary["employees"] == first_summary["employees"]
    assert second_summary["attendance"] == first_summary["attendance"]
    assert second_summary["leave_requests"] == first_summary["leave_requests"]


def test_constraints_reject_invalid_data(seeded_db):
    db_file, _ = seeded_db
    conn = get_connection(db_file)
    try:
        # Invalid role CHECK constraint
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO employees (employee_id, full_name, department_id, position, start_date, role)
                VALUES ('NV999', 'Test Invalid', 'DEPT_SALES', 'Test', '2026-01-01', 'superadmin')
                """
            )

        # Invalid foreign key on attendance
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO attendance (employee_id, work_date, status)
                VALUES ('NV_NOT_EXIST', '2026-10-01', 'present')
                """
            )
    finally:
        conn.close()


def test_scenarios_s1_to_s7_and_bonus_r3(seeded_db):
    db_file, _ = seeded_db
    conn = get_connection(db_file)
    try:
        # S1: NV007 has 8 late days (15-40 minutes) in Oct 2026
        s1_rows = conn.execute(
            """
            SELECT work_date, late_minutes FROM v_attendance_daily
            WHERE employee_id = 'NV007' AND period = '2026-10' AND is_late = 1
            """
        ).fetchall()
        assert len(s1_rows) == 8
        for r in s1_rows:
            assert 15 <= r["late_minutes"] <= 40

        # S2: NV015 has 4 missing check_out days in Sep 2026
        s2_count = conn.execute(
            """
            SELECT COUNT(*) FROM v_attendance_daily
            WHERE employee_id = 'NV015' AND period = '2026-09'
              AND status = 'present' AND check_in IS NOT NULL AND check_out IS NULL
            """
        ).fetchone()[0]
        assert s2_count == 4

        # S3: NV023 has 10 days in Nov 2026 with exact 08:29:00 and 17:31:00
        s3_count = conn.execute(
            """
            SELECT COUNT(*) FROM v_attendance_daily
            WHERE employee_id = 'NV023' AND period = '2026-11'
              AND substr(check_in, 12, 8) = '08:29:00'
              AND substr(check_out, 12, 8) = '17:31:00'
            """
        ).fetchone()[0]
        assert s3_count == 10

        # S4: NV031 has 3 approved leave requests within +-3 days of 2026-09-02
        s4_count = conn.execute(
            """
            SELECT COUNT(*) FROM v_leave_requests
            WHERE employee_id = 'NV031' AND status = 'approved'
              AND ABS(julianday(from_date) - julianday('2026-09-02')) <= 3
            """
        ).fetchone()[0]
        assert s4_count == 3

        # S5: DEPT_SALES (Kinh doanh) has 6 people on approved leave on 2026-10-16
        s5_count = conn.execute(
            """
            SELECT COUNT(DISTINCT employee_id) FROM v_leave_requests
            WHERE department_id = 'DEPT_SALES' AND status = 'approved'
              AND '2026-10-16' BETWEEN from_date AND to_date
            """
        ).fetchone()[0]
        assert s5_count == 6

        # S6: NV045 has 3 Saturday punches in Oct 2026
        s6_count = conn.execute(
            """
            SELECT COUNT(*) FROM v_attendance_daily
            WHERE employee_id = 'NV045' AND period = '2026-10'
              AND status = 'present' AND is_weekend = 1
            """
        ).fetchone()[0]
        assert s6_count == 3

        # S7: NV052 has 2 approved annual leave requests totaling 17 calendar days inclusive (> 12 balance)
        s7_row = conn.execute(
            """
            SELECT COUNT(*) AS req_cnt, SUM(leave_days) AS total_days
            FROM v_leave_requests
            WHERE employee_id = 'NV052' AND leave_type = 'annual' AND status = 'approved'
            """
        ).fetchone()
        assert s7_row["req_cnt"] == 2
        assert s7_row["total_days"] == 17

        # Bonus R3 check: NV060 has 6 low work hours (< 7h) days in Oct 2026
        r3_count = conn.execute(
            """
            SELECT COUNT(*) FROM v_attendance_daily
            WHERE employee_id = 'NV060' AND period = '2026-10'
              AND status = 'present' AND check_in IS NOT NULL AND check_out IS NOT NULL
              AND work_hours < 7.0
            """
        ).fetchone()[0]
        assert r3_count == 6
    finally:
        conn.close()
