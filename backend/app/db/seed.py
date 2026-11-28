from __future__ import annotations

import argparse
import datetime
import os
from pathlib import Path
import random
from typing import Dict, List, Optional, Tuple
import bcrypt

from app.db.connection import get_connection, init_db
from app.db.migrations import seed_rbac_and_system_defaults

SEED_RANDOM = 2026
DEV_DEFAULT_PASSWORD = os.getenv("DEV_SEED_PASSWORD", "Demo@123")

DEPARTMENTS: List[Tuple[str, str]] = [
    ("DEPT_SALES", "Kinh doanh"),
    ("DEPT_TECH", "Kỹ thuật"),
    ("DEPT_HR", "Nhân sự"),
    ("DEPT_MKT", "Marketing"),
    ("DEPT_OPS", "Vận hành"),
]

HOLIDAYS_2026: List[Tuple[str, str]] = [
    ("2026-01-01", "Tết Dương lịch"),
    ("2026-04-30", "Ngày Giải phóng miền Nam"),
    ("2026-05-01", "Ngày Quốc tế Lao động"),
    ("2026-09-02", "Ngày Quốc khánh 02/09"),
]

LAST_NAMES = [
    "Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Huỳnh", "Phan", "Vũ", "Võ", "Đặng", "Bùi", "Đỗ", "Hồ", "Ngô", "Dương",
]
MIDDLE_NAMES = ["Văn", "Thị", "Minh", "Hoàng", "Thanh", "Đức", "Ngọc", "Quang", "Thu", "Hữu", "Anh", "Khánh"]
FIRST_NAMES = [
    "An", "Bình", "Cường", "Dũng", "Em", "Giang", "Hà", "Hải", "Hùng", "Hương",
    "Khanh", "Lan", "Linh", "Long", "Mai", "Nam", "Nga", "Ngọc", "Phong", "Phúc",
    "Quân", "Quỳnh", "Sơn", "Tâm", "Thảo", "Thành", "Trang", "Trung", "Tú", "Tuấn",
]

POSITIONS_BY_DEPT: Dict[str, List[str]] = {
    "DEPT_SALES": ["Chuyên viên Kinh doanh", "Nhân viên Tư vấn", "Chuyên viên Phát triển khách hàng"],
    "DEPT_TECH": ["Kỹ sư Phần mềm", "Kỹ sư Kiểm thử QA", "Kỹ sư Dữ liệu"],
    "DEPT_HR": ["Chuyên viên Nhân sự", "Chuyên viên Hành chính", "Chuyên viên C&B"],
    "DEPT_MKT": ["Chuyên viên Marketing", "Chuyên viên Nội dung", "Chuyên viên Truyền thông"],
    "DEPT_OPS": ["Chuyên viên Vận hành", "Điều phối viên", "Chuyên viên Hỗ trợ khách hàng"],
}


def _generate_full_name(rng: random.Random) -> str:
    return f"{rng.choice(LAST_NAMES)} {rng.choice(MIDDLE_NAMES)} {rng.choice(FIRST_NAMES)}"


def _iter_dates(start: datetime.date, end: datetime.date):
    cur = start
    while cur <= end:
        yield cur
        cur += datetime.timedelta(days=1)


def _format_dt(d: datetime.date, h: int, m: int, s: int) -> str:
    return f"{d.isoformat()} {h:02d}:{m:02d}:{s:02d}"


def seed_database(db_path: Optional[Path | str] = None, reset: bool = False) -> Dict[str, int]:
    """Initialize schema and deterministically seed 80 employees, 5 departments, 6 months (06-11/2026) and scenarios S1-S7."""
    if os.getenv("APP_ENV", "development").lower() == "production":
        raise RuntimeError("Từ chối chạy seed dữ liệu giả lập trong môi trường production (APP_ENV=production).")
    path = init_db(db_path)
    conn = get_connection(path, readonly=False)
    try:
        existing_emp = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        if existing_emp > 0 and not reset:
            return {
                "departments": conn.execute("SELECT COUNT(*) FROM departments").fetchone()[0],
                "employees": existing_emp,
                "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
                "attendance": conn.execute("SELECT COUNT(*) FROM attendance").fetchone()[0],
                "leave_requests": conn.execute("SELECT COUNT(*) FROM leave_requests").fetchone()[0],
                "skipped_existing": 1,
            }

        if reset and existing_emp > 0:
            conn.execute("PRAGMA foreign_keys = OFF;")
            for table in [
                "document_chunks",
                "company_documents",
                "kiosk_devices",
                "revoked_tokens",
                "system_settings",
                "role_permissions",
                "user_roles",
                "permissions",
                "roles",
                "leave_approval_logs",
                "activity_logs",
                "import_logs",
                "query_audit_log",
                "anomalies",
                "overtime_requests",
                "leave_requests",
                "attendance",
                "users",
                "employees",
                "holidays",
                "departments",
            ]:
                conn.execute(f"DELETE FROM {table};")
            conn.execute("DELETE FROM sqlite_sequence;")
            conn.execute("PRAGMA foreign_keys = ON;")

        rng = random.Random(SEED_RANDOM)

        # 1. Departments
        conn.executemany(
            "INSERT INTO departments (department_id, name) VALUES (?, ?)",
            DEPARTMENTS,
        )

        # 2. Holidays
        conn.executemany(
            "INSERT INTO holidays (holiday_date, name) VALUES (?, ?)",
            HOLIDAYS_2026,
        )
        holiday_set = {h[0] for h in HOLIDAYS_2026}

        # 3. Employees (80 total: 16 per department)
        # Key leadership & demo accounts:
        # NV001: Manager of DEPT_SALES
        # NV002: HR Admin (DEPT_HR)
        # NV003: Manager of DEPT_TECH
        # NV004: Manager of DEPT_MKT
        # NV005: Manager of DEPT_OPS
        # NV006: Secondary HR Admin (DEPT_HR) - allows safe testing of last-HR protection
        dept_managers: Dict[str, str] = {
            "DEPT_SALES": "NV001",
            "DEPT_HR": "NV002",
            "DEPT_TECH": "NV003",
            "DEPT_MKT": "NV004",
            "DEPT_OPS": "NV005",
        }

        employees_rows = [
            ("NV001", "Nguyễn Văn Bình", "DEPT_SALES", "Trưởng phòng Kinh doanh", None, "2023-03-01", 12.0, "manager", "active", "manager.sales@company.vn", "0901000001"),
            ("NV002", "Nguyễn Thị Mai", "DEPT_HR", "Trưởng bộ phận Nhân sự", None, "2022-08-15", 12.0, "hr", "active", "hr@company.vn", "0901000002"),
            ("NV003", "Trần Quốc Hùng", "DEPT_TECH", "Trưởng phòng Kỹ thuật", None, "2023-01-10", 12.0, "manager", "active", "manager.tech@company.vn", "0901000003"),
            ("NV004", "Lê Thu Thảo", "DEPT_MKT", "Trưởng phòng Marketing", None, "2023-06-01", 12.0, "manager", "active", "manager.mkt@company.vn", "0901000004"),
            ("NV005", "Phạm Minh Tuấn", "DEPT_OPS", "Trưởng phòng Vận hành", None, "2023-09-01", 12.0, "manager", "active", "manager.ops@company.vn", "0901000005"),
            ("NV006", "Đặng Ngọc Linh", "DEPT_HR", "Chuyên viên Nhân sự cấp cao", "NV002", "2024-02-01", 12.0, "hr", "active", "hr2@company.vn", "0901000006"),
        ]

        # Remaining 74 employees (NV007..NV080) -> exactly 16 per department:
        # DEPT_SALES: NV007..NV021 (15 + NV001 = 16) -> includes NV007 (S1), NV008..NV013 (S5), NV015 (S2)
        # DEPT_TECH : NV022..NV036 (15 + NV003 = 16) -> includes NV023 (S3), NV031 (S4)
        # DEPT_HR   : NV037..NV050 (14 + NV002, NV006 = 16) -> includes NV045 (S6)
        # DEPT_MKT  : NV051..NV065 (15 + NV004 = 16) -> includes NV052 (S7), NV060 (R3 bonus)
        # DEPT_OPS  : NV066..NV080 (15 + NV005 = 16)
        dept_ranges = [
            ("DEPT_SALES", range(7, 22)),
            ("DEPT_TECH", range(22, 37)),
            ("DEPT_HR", range(37, 51)),
            ("DEPT_MKT", range(51, 66)),
            ("DEPT_OPS", range(66, 81)),
        ]

        fixed_names = {
            "NV007": "Nguyễn Văn An",
            "NV015": "Trần Minh Đức",
            "NV023": "Lê Hoàng Nam",
            "NV031": "Phạm Thị Hương",
            "NV045": "Vũ Quang Phong",
            "NV052": "Hoàng Thu Trang",
            "NV060": "Bùi Thanh Tùng",
        }

        for dept_id, id_range in dept_ranges:
            mgr_id = dept_managers[dept_id]
            positions = POSITIONS_BY_DEPT[dept_id]
            for num in id_range:
                emp_id = f"NV{num:03d}"
                full_name = fixed_names.get(emp_id, _generate_full_name(rng))
                position = rng.choice(positions)
                start_year = rng.choice([2023, 2024, 2025])
                start_month = rng.randint(1, 12)
                start_day = rng.randint(1, 28)
                start_date = f"{start_year:04d}-{start_month:02d}-{start_day:02d}"
                email = f"{emp_id.lower()}@company.vn"
                phone = f"0901{num:06d}"
                role = "employee"
                row_mgr_id: Optional[str] = mgr_id
                # Seed Executive (NV079) and Technical Admin (NV080) after RNG draws so NV007..NV078 stay 100% identical
                if emp_id == "NV079":
                    full_name = "Trần Minh Quang"
                    position = "Giám đốc Điều hành"
                    row_mgr_id = None
                    role = "executive"
                    email = "director@company.vn"
                elif emp_id == "NV080":
                    full_name = "Nguyễn Hải Đăng"
                    position = "Quản trị viên Hệ thống"
                    row_mgr_id = None
                    role = "admin"
                    email = "admin@company.vn"
                employees_rows.append(
                    (emp_id, full_name, dept_id, position, row_mgr_id, start_date, 12.0, role, "active", email, phone)
                )

        conn.executemany(
            """
            INSERT INTO employees (
                employee_id, full_name, department_id, position, manager_id,
                start_date, annual_leave_balance, role, employment_status, email, phone
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            employees_rows,
        )

        # 4. Users (1-1 with employees, bcrypt password hashes, never plaintext)
        password_hash = bcrypt.hashpw(DEV_DEFAULT_PASSWORD.encode("utf-8"), bcrypt.gensalt(rounds=4)).decode("utf-8")
        users_rows = []
        for idx, emp in enumerate(employees_rows, start=1):
            emp_id = emp[0]
            email = emp[9]
            user_id = f"USR{idx:03d}"
            users_rows.append((user_id, email, password_hash, emp_id, 1, None, 0))

        conn.executemany(
            """
            INSERT INTO users (
                user_id, username, password_hash, employee_id,
                is_active, last_login_at, must_change_password
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            users_rows,
        )

        # 5. Deterministic Leave Requests (including Scenarios S4, S5, S7 + realistic background leaves)
        leave_rows: List[Tuple] = []
        approved_leave_days_by_emp: Dict[str, set[str]] = {}

        def add_leave(
            emp_id: str,
            leave_type: str,
            from_d: str,
            to_d: str,
            reason: str,
            status: str,
            reviewed_by: Optional[str],
            decision_note: Optional[str] = None,
            requires_executive_approval: int = 0,
        ):
            created_at = f"{from_d} 09:00:00"
            reviewed_at = f"{from_d} 11:30:00" if status in ("approved", "rejected") else None
            leave_rows.append(
                (
                    emp_id,
                    leave_type,
                    from_d,
                    to_d,
                    reason,
                    status,
                    requires_executive_approval,
                    created_at,
                    reviewed_by,
                    reviewed_at,
                    decision_note,
                )
            )
            if status == "approved":
                s_dt = datetime.date.fromisoformat(from_d)
                e_dt = datetime.date.fromisoformat(to_d)
                day_set = approved_leave_days_by_emp.setdefault(emp_id, set())
                for d in _iter_dates(s_dt, e_dt):
                    day_set.add(d.isoformat())

        # S4: NV031 - 3 approved leave requests within +-3 days of holiday 2026-09-02
        add_leave("NV031", "annual", "2026-08-31", "2026-08-31", "Nghỉ phép việc gia đình trước lễ", "approved", "NV003", "Đã duyệt")
        add_leave("NV031", "annual", "2026-09-03", "2026-09-03", "Nghỉ nối tiếp sau lễ 02/09", "approved", "NV003", "Đã duyệt")
        add_leave("NV031", "personal", "2026-09-04", "2026-09-04", "Giải quyết việc cá nhân sau lễ", "approved", "NV003", "Đã duyệt")

        # S5: DEPT_SALES - 6 employees on approved leave on 2026-10-16 (6/16 = 37.5% >= 25%)
        for s5_emp in ["NV008", "NV009", "NV010", "NV011", "NV012", "NV013"]:
            add_leave(s5_emp, "annual", "2026-10-16", "2026-10-16", "Nghỉ phép năm theo kế hoạch cá nhân", "approved", "NV001", "Đã duyệt")

        # S7: NV052 - 2 approved annual leave requests totaling 17 calendar days inclusive (> balance 12)
        # 2026-07-06..2026-07-15 = 10 calendar days; 2026-09-14..2026-09-20 = 7 calendar days => 17 days
        add_leave("NV052", "annual", "2026-07-06", "2026-07-15", "Nghỉ phép năm du lịch gia đình đợt 1", "approved", "NV004", "Đã duyệt")
        add_leave("NV052", "annual", "2026-09-14", "2026-09-20", "Nghỉ phép năm về quê đợt 2", "approved", "NV004", "Đã duyệt")

        # Realistic additional leave requests (pending, approved, rejected) for UI demo
        add_leave("NV007", "annual", "2026-11-18", "2026-11-19", "Nghỉ phép giải quyết việc gia đình", "pending", None, None)
        add_leave("NV014", "sick", "2026-10-22", "2026-10-23", "Khám sức khỏe định kỳ", "pending", None, None)
        add_leave("NV016", "personal", "2026-10-27", "2026-10-27", "Đưa người nhà đi viện", "rejected", "NV001", "Phòng đang cao điểm chốt doanh số cuối tháng")
        add_leave("NV024", "annual", "2026-10-08", "2026-10-09", "Nghỉ phép năm cá nhân", "approved", "NV003", "Đã duyệt")
        add_leave("NV025", "annual", "2026-11-24", "2026-11-25", "Nghỉ phép năm", "pending", None, None)
        add_leave("NV038", "sick", "2026-08-12", "2026-08-13", "Nghỉ ốm có giấy bác sĩ", "approved", "NV002", "Đã duyệt")
        add_leave("NV053", "annual", "2026-10-12", "2026-10-13", "Nghỉ phép năm", "approved", "NV004", "Đã duyệt")
        add_leave("NV067", "annual", "2026-11-05", "2026-11-06", "Nghỉ phép cá nhân", "approved", "NV005", "Đã duyệt")
        add_leave(
            "NV068",
            "personal",
            "2026-11-20",
            "2026-11-20",
            "Đề xuất nghỉ đặc biệt cần Ban Điều hành phê duyệt",
            "pending",
            None,
            None,
            requires_executive_approval=1,
        )

        conn.executemany(
            """
            INSERT INTO leave_requests (
                employee_id, leave_type, from_date, to_date, reason, status,
                requires_executive_approval, created_at, reviewed_by, reviewed_at, decision_note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            leave_rows,
        )

        # BUG-10: Seed initial leave_approval_logs idempotently for every seeded leave request
        emp_to_user = {
            r["employee_id"]: r["user_id"]
            for r in conn.execute("SELECT employee_id, user_id FROM users").fetchall()
        }
        seeded_leaves = conn.execute(
            """
            SELECT request_id, employee_id, reason, status, created_at, reviewed_by, reviewed_at, decision_note
            FROM leave_requests
            ORDER BY request_id ASC
            """
        ).fetchall()
        for lr in seeded_leaves:
            req_id = lr["request_id"]
            submitter_uid = emp_to_user.get(lr["employee_id"])
            if submitter_uid:
                exists_sub = conn.execute(
                    "SELECT 1 FROM leave_approval_logs WHERE request_id = ? AND action = 'submit'",
                    (req_id,),
                ).fetchone()
                if not exists_sub:
                    conn.execute(
                        """
                        INSERT INTO leave_approval_logs (request_id, actor_user_id, action, note, created_at)
                        VALUES (?, ?, 'submit', ?, ?)
                        """,
                        (req_id, submitter_uid, lr["reason"], lr["created_at"]),
                    )
            if lr["status"] in ("approved", "rejected") and lr["reviewed_by"]:
                rev_action = "approve" if lr["status"] == "approved" else "reject"
                reviewer_uid = emp_to_user.get(lr["reviewed_by"])
                if reviewer_uid:
                    exists_rev = conn.execute(
                        "SELECT 1 FROM leave_approval_logs WHERE request_id = ? AND action = ?",
                        (req_id, rev_action),
                    ).fetchone()
                    if not exists_rev:
                        conn.execute(
                            """
                            INSERT INTO leave_approval_logs (request_id, actor_user_id, action, note, created_at)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                req_id,
                                reviewer_uid,
                                rev_action,
                                lr["decision_note"] or ("Đã duyệt" if rev_action == "approve" else "Từ chối"),
                                lr["reviewed_at"] or lr["created_at"],
                            ),
                        )

        # 6. Attendance records: 2026-06-01 to 2026-11-30 (6 months)
        start_period = datetime.date(2026, 6, 1)
        end_period = datetime.date(2026, 11, 30)

        # Specific scenario date sets
        # S1: NV007 - 8 late days (15-40 mins late) in Oct 2026
        s1_dates_minutes = {
            "2026-10-02": 18,
            "2026-10-05": 25,
            "2026-10-08": 32,
            "2026-10-12": 17,
            "2026-10-15": 40,
            "2026-10-20": 22,
            "2026-10-23": 15,
            "2026-10-28": 35,
        }
        # S2: NV015 - 4 missing check_out days in Sep 2026
        s2_dates = {"2026-09-07", "2026-09-11", "2026-09-18", "2026-09-25"}
        # S3: NV023 - 10 consecutive working days in Nov 2026 identical 08:29:00 / 17:31:00
        s3_dates = {
            "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06",
            "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13",
        }
        # S6: NV045 - 3 Saturdays in Oct 2026 with present punch
        s6_saturdays = {"2026-10-03", "2026-10-10", "2026-10-17"}
        # Bonus R3: NV060 - 6 low_hours (< 7h) days in Oct 2026 with distinct timestamps (so R6 does NOT false-trigger!)
        r3_schedule = {
            "2026-10-05": ((8, 25, 11), (15, 10, 22)),
            "2026-10-07": ((8, 28, 43), (15, 18, 5)),
            "2026-10-12": ((8, 31, 9), (15, 22, 47)),
            "2026-10-15": ((8, 27, 30), (15, 15, 18)),
            "2026-10-19": ((8, 33, 14), (15, 24, 33)),
            "2026-10-22": ((8, 29, 52), (15, 12, 41)),
        }

        scenario_controlled_emps = {"NV007", "NV015", "NV023", "NV031", "NV045", "NV052", "NV060"}

        attendance_rows: List[Tuple] = []
        all_emp_ids = [row[0] for row in employees_rows]

        for emp_id in all_emp_ids:
            leave_dates = approved_leave_days_by_emp.get(emp_id, set())
            for cur_date in _iter_dates(start_period, end_period):
                d_str = cur_date.isoformat()
                weekday = cur_date.weekday()  # 0=Mon .. 6=Sun

                # S6 Saturday punch for NV045
                if emp_id == "NV045" and d_str in s6_saturdays:
                    attendance_rows.append(
                        (emp_id, d_str, _format_dt(cur_date, 8, 40, 12), _format_dt(cur_date, 16, 15, 30), "present", "biometric")
                    )
                    continue

                # Skip weekends for normal days
                if weekday >= 5:
                    continue

                # Public holiday
                if d_str in holiday_set:
                    attendance_rows.append((emp_id, d_str, None, None, "holiday", "system"))
                    continue

                # Approved leave day
                if d_str in leave_dates:
                    attendance_rows.append((emp_id, d_str, None, None, "on_leave", "leave_system"))
                    continue

                # Scenario S1: NV007 Oct 2026 (strictly 15-40 minutes late)
                if emp_id == "NV007" and d_str in s1_dates_minutes:
                    late_min = s1_dates_minutes[d_str]
                    in_total_min = 8 * 60 + 30 + late_min
                    in_h, in_m = divmod(in_total_min, 60)
                    in_s = 0 if late_min == 40 else rng.randint(0, 29)
                    attendance_rows.append(
                        (emp_id, d_str, _format_dt(cur_date, in_h, in_m, in_s), _format_dt(cur_date, 17, rng.randint(30, 48), rng.randint(0, 59)), "present", "biometric")
                    )
                    continue

                # Scenario S2: NV015 Sep 2026 missing check-out
                if emp_id == "NV015" and d_str in s2_dates:
                    attendance_rows.append(
                        (emp_id, d_str, _format_dt(cur_date, 8, rng.randint(20, 32), rng.randint(0, 59)), None, "present", "biometric")
                    )
                    continue

                # Scenario S3: NV023 Nov 2026 exact 08:29:00 / 17:31:00
                if emp_id == "NV023" and d_str in s3_dates:
                    attendance_rows.append(
                        (emp_id, d_str, _format_dt(cur_date, 8, 29, 0), _format_dt(cur_date, 17, 31, 0), "present", "biometric")
                    )
                    continue

                # Bonus R3: NV060 Oct 2026 low work hours (< 7h, distinct timestamps to avoid false R6)
                if emp_id == "NV060" and d_str in r3_schedule:
                    (ih, im, isec), (oh, om, osec) = r3_schedule[d_str]
                    attendance_rows.append(
                        (emp_id, d_str, _format_dt(cur_date, ih, im, isec), _format_dt(cur_date, oh, om, osec), "present", "biometric")
                    )
                    continue

                # Regular deterministic attendance
                if emp_id in scenario_controlled_emps:
                    # Keep non-scenario days cleanly on-time for scenario employees
                    in_m = rng.randint(15, 33)
                    in_s = rng.randint(1, 58)
                    out_m = rng.randint(30, 52)
                    out_s = rng.randint(1, 58)
                    attendance_rows.append(
                        (emp_id, d_str, _format_dt(cur_date, 8, in_m, in_s), _format_dt(cur_date, 17, out_m, out_s), "present", "biometric")
                    )
                else:
                    roll = rng.random()
                    if roll < 0.015:
                        # Occasional absent day
                        attendance_rows.append((emp_id, d_str, None, None, "absent", "biometric"))
                    elif roll < 0.065:
                        # Occasional minor late day (6..25 mins)
                        late_min = rng.randint(6, 25)
                        in_total_min = 8 * 60 + 30 + late_min
                        in_h, in_m = divmod(in_total_min, 60)
                        attendance_rows.append(
                            (emp_id, d_str, _format_dt(cur_date, in_h, in_m, rng.randint(0, 59)), _format_dt(cur_date, 17, rng.randint(30, 50), rng.randint(0, 59)), "present", "biometric")
                        )
                    else:
                        in_m = rng.randint(10, 34)
                        in_s = rng.randint(0, 59)
                        out_m = rng.randint(30, 55)
                        out_s = rng.randint(0, 59)
                        attendance_rows.append(
                            (emp_id, d_str, _format_dt(cur_date, 8, in_m, in_s), _format_dt(cur_date, 17, out_m, out_s), "present", "biometric")
                        )

        conn.executemany(
            """
            INSERT INTO attendance (employee_id, work_date, check_in, check_out, status, source)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            attendance_rows,
        )

        # Seed RBAC 5 roles, permissions, role_permissions, user_roles, system_settings, kiosk_devices & RAG docs
        seed_rbac_and_system_defaults(conn, sync_strict_role_matrix=True)

        # Initial seed activity log
        conn.execute(
            """
            INSERT INTO activity_logs (actor_user_id, action, entity_type, entity_id, before_json, after_json)
            VALUES ('USR080', 'seed_database', 'system', 'initial', NULL, '{"employees": 80, "departments": 5, "roles": 5}')
            """
        )

        conn.commit()
        return {
            "departments": len(DEPARTMENTS),
            "employees": len(employees_rows),
            "users": len(users_rows),
            "attendance": len(attendance_rows),
            "leave_requests": len(leave_rows),
            "skipped_existing": 0,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed HR Attendance Copilot SQLite database")
    parser.add_argument("--reset", action="store_true", help="Reset and re-seed all tables cleanly")
    parser.add_argument("--db", type=str, default=None, help="Optional custom SQLite database path")
    args = parser.parse_args()
    summary = seed_database(db_path=args.db, reset=args.reset)
    print("Seed summary:", summary)
