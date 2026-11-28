from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.db.connection import is_postgres_connection

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"
SQL_PG_DIR = Path(__file__).resolve().parents[2] / "sql_postgres"

RULE_SQL_FILES: List[tuple[str, str, str]] = [
    ("R1", "late_repeated", "r1_late_repeated.sql"),
    ("R2", "missing_punch", "r2_missing_punch.sql"),
    ("R3", "low_hours", "r3_low_hours.sql"),
    ("R4", "leave_near_holiday", "r4_leave_near_holiday.sql"),
    ("R5", "leave_cluster", "r5_leave_cluster.sql"),
    ("R6", "identical_punch", "r6_identical_punch.sql"),
    ("R7", "weekend_punch", "r7_weekend_punch.sql"),
    ("R8", "leave_over_balance", "r8_leave_over_balance.sql"),
]

NEUTRAL_DISCLAIMER = "Đây là dấu hiệu cần kiểm tra từ dữ liệu chấm công/nghỉ phép; chưa phải kết luận vi phạm."


def _build_anomaly_record(rule_code: str, anomaly_type: str, row: sqlite3.Row) -> Dict[str, Any]:
    r = dict(row)

    if rule_code == "R1":
        dedup_key = f"R1:{r['employee_id']}:{r['period']}"
        evidence = {
            "rule_code": "R1",
            "employee_id": r["employee_id"],
            "period": r["period"],
            "late_days": int(r["late_days"]),
            "threshold_days": 5,
            "grace_minutes": 5,
            "min_late_minutes": int(r["min_late_minutes"]),
            "max_late_minutes": int(r["max_late_minutes"]),
            "sample_dates": (r["sample_dates"] or "").split("; ") if r["sample_dates"] else [],
        }
        explanation = (
            f"Nhân viên {r['employee_id']} ({r['full_name']}) ghi nhận {r['late_days']} ngày vào sau giờ quy định "
            f"quá 5 phút trong tháng {r['period']} (từ {r['min_late_minutes']} đến {r['max_late_minutes']} phút). "
            f"{NEUTRAL_DISCLAIMER}"
        )
        return {
            "employee_id": r["employee_id"],
            "department_id": r["department_id"],
            "scope_type": "employee",
            "rule_code": rule_code,
            "anomaly_type": anomaly_type,
            "severity": r["severity"],
            "period": r["period"],
            "evidence": json.dumps(evidence, ensure_ascii=False),
            "explanation": explanation,
            "dedup_key": dedup_key,
        }

    if rule_code == "R2":
        dedup_key = f"R2:{r['employee_id']}:{r['period']}"
        evidence = {
            "rule_code": "R2",
            "employee_id": r["employee_id"],
            "period": r["period"],
            "missing_days": int(r["missing_days"]),
            "threshold_days": 2,
            "sample_dates": (r["sample_dates"] or "").split("; ") if r["sample_dates"] else [],
        }
        explanation = (
            f"Nhân viên {r['employee_id']} ({r['full_name']}) có {r['missing_days']} ngày trong tháng {r['period']} "
            f"thiếu dữ liệu giờ vào hoặc giờ ra. Cần đối chiếu bổ sung để tránh tính thiếu công. {NEUTRAL_DISCLAIMER}"
        )
        return {
            "employee_id": r["employee_id"],
            "department_id": r["department_id"],
            "scope_type": "employee",
            "rule_code": rule_code,
            "anomaly_type": anomaly_type,
            "severity": r["severity"],
            "period": r["period"],
            "evidence": json.dumps(evidence, ensure_ascii=False),
            "explanation": explanation,
            "dedup_key": dedup_key,
        }

    if rule_code == "R3":
        dedup_key = f"R3:{r['employee_id']}:{r['period']}"
        evidence = {
            "rule_code": "R3",
            "employee_id": r["employee_id"],
            "period": r["period"],
            "low_hour_days": int(r["low_hour_days"]),
            "threshold_days": 5,
            "threshold_hours": 7.0,
            "avg_work_hours": float(r["avg_work_hours"]),
            "sample_dates": (r["sample_dates"] or "").split("; ") if r["sample_dates"] else [],
        }
        explanation = (
            f"Nhân viên {r['employee_id']} ({r['full_name']}) có {r['low_hour_days']} ngày làm việc dưới 7 giờ "
            f"trong tháng {r['period']} (trung bình {r['avg_work_hours']} giờ/ngày ở các ngày này). {NEUTRAL_DISCLAIMER}"
        )
        return {
            "employee_id": r["employee_id"],
            "department_id": r["department_id"],
            "scope_type": "employee",
            "rule_code": rule_code,
            "anomaly_type": anomaly_type,
            "severity": r["severity"],
            "period": r["period"],
            "evidence": json.dumps(evidence, ensure_ascii=False),
            "explanation": explanation,
            "dedup_key": dedup_key,
        }

    if rule_code == "R4":
        dedup_key = f"R4:{r['employee_id']}:{r['holiday_date']}"
        evidence = {
            "rule_code": "R4",
            "employee_id": r["employee_id"],
            "holiday_date": r["holiday_date"],
            "holiday_name": r["holiday_name"],
            "request_count": int(r["request_count"]),
            "window_days": 3,
            "leave_ranges": (r["leave_ranges"] or "").split("; ") if r["leave_ranges"] else [],
        }
        explanation = (
            f"Nhân viên {r['employee_id']} ({r['full_name']}) có {r['request_count']} đơn nghỉ phép đã duyệt "
            f"nằm trong khoảng ±3 ngày quanh kỳ lễ {r['holiday_name']} ({r['holiday_date']}). {NEUTRAL_DISCLAIMER}"
        )
        return {
            "employee_id": r["employee_id"],
            "department_id": r["department_id"],
            "scope_type": "employee",
            "rule_code": rule_code,
            "anomaly_type": anomaly_type,
            "severity": r["severity"],
            "period": r["period"],
            "evidence": json.dumps(evidence, ensure_ascii=False),
            "explanation": explanation,
            "dedup_key": dedup_key,
        }

    if rule_code == "R5":
        # Department-scoped anomaly: never falsely assigned as an individual employee violation!
        dedup_key = f"R5:{r['department_id']}:{r['work_date']}"
        emp_ids = sorted([e for e in (r["employee_ids"] or "").split(",") if e])
        evidence = {
            "rule_code": "R5",
            "scope": "department",
            "department_id": r["department_id"],
            "department_name": r["department_name"],
            "work_date": r["work_date"],
            "leave_count": int(r["leave_count"]),
            "dept_headcount": int(r["dept_headcount"]),
            "leave_pct": float(r["leave_pct"]),
            "employee_ids": emp_ids,
        }
        explanation = (
            f"Cảnh báo cấp phòng: Phòng {r['department_name']} có {r['leave_count']}/{r['dept_headcount']} "
            f"nhân sự ({r['leave_pct']}%) cùng nghỉ phép vào ngày {r['work_date']}. Cần rà soát điều phối nhân lực. "
            f"{NEUTRAL_DISCLAIMER}"
        )
        return {
            "employee_id": None,
            "department_id": r["department_id"],
            "scope_type": "department",
            "rule_code": rule_code,
            "anomaly_type": anomaly_type,
            "severity": r["severity"],
            "period": r["period"],
            "evidence": json.dumps(evidence, ensure_ascii=False),
            "explanation": explanation,
            "dedup_key": dedup_key,
        }

    if rule_code == "R6":
        dedup_key = f"R6:{r['employee_id']}:{r['period']}:{r['exact_check_in']}:{r['exact_check_out']}"
        evidence = {
            "rule_code": "R6",
            "employee_id": r["employee_id"],
            "period": r["period"],
            "identical_days": int(r["identical_days"]),
            "threshold_days": 5,
            "exact_check_in": r["exact_check_in"],
            "exact_check_out": r["exact_check_out"],
            "sample_dates": (r["sample_dates"] or "").split("; ") if r["sample_dates"] else [],
        }
        explanation = (
            f"Nhân viên {r['employee_id']} ({r['full_name']}) có {r['identical_days']} ngày trong tháng {r['period']} "
            f"ghi nhận giờ vào ({r['exact_check_in']}) và giờ ra ({r['exact_check_out']}) trùng khớp đến từng giây. "
            f"Cần kiểm tra thiết bị chấm công hoặc nguồn đồng bộ dữ liệu. {NEUTRAL_DISCLAIMER}"
        )
        return {
            "employee_id": r["employee_id"],
            "department_id": r["department_id"],
            "scope_type": "employee",
            "rule_code": rule_code,
            "anomaly_type": anomaly_type,
            "severity": r["severity"],
            "period": r["period"],
            "evidence": json.dumps(evidence, ensure_ascii=False),
            "explanation": explanation,
            "dedup_key": dedup_key,
        }

    if rule_code == "R7":
        dedup_key = f"R7:{r['employee_id']}:{r['period']}"
        evidence = {
            "rule_code": "R7",
            "employee_id": r["employee_id"],
            "period": r["period"],
            "weekend_holiday_days": int(r["weekend_holiday_days"]),
            "sample_dates": (r["sample_dates"] or "").split("; ") if r["sample_dates"] else [],
            "overtime_check": "Đã đối chiếu bảng overtime_requests (chưa có đơn làm thêm được duyệt)",
        }
        explanation = (
            f"Nhân viên {r['employee_id']} ({r['full_name']}) có {r['weekend_holiday_days']} ngày chấm công vào cuối tuần "
            f"hoặc ngày lễ trong tháng {r['period']} khi chưa có đơn làm thêm được duyệt. {NEUTRAL_DISCLAIMER}"
        )
        return {
            "employee_id": r["employee_id"],
            "department_id": r["department_id"],
            "scope_type": "employee",
            "rule_code": rule_code,
            "anomaly_type": anomaly_type,
            "severity": r["severity"],
            "period": r["period"],
            "evidence": json.dumps(evidence, ensure_ascii=False),
            "explanation": explanation,
            "dedup_key": dedup_key,
        }

    # R8: leave_over_balance
    dedup_key = f"R8:{r['employee_id']}:{r['period']}"
    evidence = {
        "rule_code": "R8",
        "employee_id": r["employee_id"],
        "annual_leave_balance": float(r["annual_leave_balance"]),
        "approved_annual_days": float(r["approved_annual_days"]),
        "excess_days": float(r["excess_days"]),
        "request_count": int(r["request_count"]),
        "leave_days_method": "calendar_days_inclusive",
        "leave_ranges": (r["leave_ranges"] or "").split("; ") if r["leave_ranges"] else [],
    }
    explanation = (
        f"Nhân viên {r['employee_id']} ({r['full_name']}) có tổng {r['approved_annual_days']} ngày phép năm đã duyệt "
        f"(tính theo ngày lịch), vượt quỹ phép {r['annual_leave_balance']} ngày là {r['excess_days']} ngày. "
        f"{NEUTRAL_DISCLAIMER}"
    )
    return {
        "employee_id": r["employee_id"],
        "department_id": r["department_id"],
        "scope_type": "employee",
        "rule_code": rule_code,
        "anomaly_type": anomaly_type,
        "severity": r["severity"],
        "period": r["period"],
        "evidence": json.dumps(evidence, ensure_ascii=False),
        "explanation": explanation,
        "dedup_key": dedup_key,
    }


def run_anomaly_scan(
    conn: sqlite3.Connection,
    period: Optional[str] = None,
    department_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute all 8 deterministic SQL rules R1-R8 and upsert anomalies idempotently (optionally scoped to one department)."""
    inserted = 0
    updated = 0
    by_rule: Dict[str, int] = {code: 0 for code, _, _ in RULE_SQL_FILES}

    sql_root = SQL_PG_DIR if is_postgres_connection(conn) else SQL_DIR
    for rule_code, anomaly_type, filename in RULE_SQL_FILES:
        sql_path = sql_root / filename
        sql_text = sql_path.read_text(encoding="utf-8")
        rows = conn.execute(sql_text, {"period": period}).fetchall()
        if department_id is not None:
            rows = [r for r in rows if r["department_id"] == department_id]
        by_rule[rule_code] = len(rows)

        for row in rows:
            rec = _build_anomaly_record(rule_code, anomaly_type, row)
            existing = conn.execute(
                "SELECT anomaly_id, review_status FROM anomalies WHERE dedup_key = ?",
                (rec["dedup_key"],),
            ).fetchone()

            if existing is None:
                conn.execute(
                    """
                    INSERT INTO anomalies (
                        employee_id, department_id, scope_type, rule_code, anomaly_type,
                        severity, period, evidence, explanation, review_status, dedup_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
                    """,
                    (
                        rec["employee_id"],
                        rec["department_id"],
                        rec["scope_type"],
                        rec["rule_code"],
                        rec["anomaly_type"],
                        rec["severity"],
                        rec["period"],
                        rec["evidence"],
                        rec["explanation"],
                        rec["dedup_key"],
                    ),
                )
                inserted += 1
            else:
                # Preserve human review_status (confirmed/dismissed), only refresh evidence/severity
                conn.execute(
                    """
                    UPDATE anomalies
                    SET severity = ?, evidence = ?, explanation = ?
                    WHERE anomaly_id = ?
                    """,
                    (rec["severity"], rec["evidence"], rec["explanation"], existing["anomaly_id"]),
                )
                updated += 1

    conn.commit()
    return {
        "period": period or "all",
        "inserted": inserted,
        "updated": updated,
        "total_detected": sum(by_rule.values()),
        "by_rule": by_rule,
    }
