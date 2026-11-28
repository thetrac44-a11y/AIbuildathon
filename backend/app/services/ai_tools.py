from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.core.security import AuthenticatedUser, build_scope_filter
from app.schemas.common import RoleEnum
from app.services.sql_guard import execute_guarded_sql


def _exec_tool_sql(
    conn: sqlite3.Connection,
    sql: str,
    params: List[Any],
    max_rows: int = 200,
) -> Dict[str, Any]:
    start = time.monotonic()
    rows = [dict(r) for r in conn.execute(sql, params).fetchmany(max_rows)]
    elapsed_ms = round((time.monotonic() - start) * 1000.0, 2)
    return {
        "rows": rows,
        "row_count": len(rows),
        "sql_text": " ".join(sql.split()),
        "execution_ms": elapsed_ms,
    }


def get_attendance_summary(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    period: str = "2026-10",
    department_name: Optional[str] = None,
) -> Dict[str, Any]:
    scope_sql, params = build_scope_filter(user, "employee_id", "department_id")
    where_parts = [scope_sql, "period = ?"]
    params.append(period)
    if department_name and user.role in (RoleEnum.hr, RoleEnum.executive):
        where_parts.append("LOWER(department_name) = LOWER(?)")
        params.append(department_name)

    sql = f"""
        SELECT
            period,
            COUNT(DISTINCT employee_id) AS employee_count,
            ROUND(COALESCE(SUM(work_hours), 0), 1) AS total_work_hours,
            SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) AS present_days,
            SUM(CASE WHEN is_late = 1 THEN 1 ELSE 0 END) AS late_days,
            SUM(CASE WHEN status = 'present' AND (check_in IS NULL OR check_out IS NULL) THEN 1 ELSE 0 END) AS missing_punch_days,
            SUM(CASE WHEN status = 'on_leave' THEN 1 ELSE 0 END) AS leave_days,
            SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) AS absent_days,
            ROUND(
                CASE WHEN SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) > 0
                     THEN SUM(CASE WHEN is_late = 1 THEN 1 ELSE 0 END) * 100.0 / SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END)
                     ELSE 0.0 END,
                2
            ) AS late_rate_pct
        FROM v_attendance_daily
        WHERE {' AND '.join(where_parts)}
        GROUP BY period
    """
    res = _exec_tool_sql(conn, sql, params)
    res["tool_name"] = "get_attendance_summary"
    return res


def get_leave_by_department(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    period: Optional[str] = None,
) -> Dict[str, Any]:
    scope_sql, params = build_scope_filter(user, "employee_id", "department_id")
    where_parts = [scope_sql]
    if period:
        where_parts.append("period = ?")
        params.append(period)

    sql = f"""
        SELECT
            department_id,
            department_name,
            COUNT(*) AS total_requests,
            SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) AS approved_requests,
            SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_requests,
            SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) AS rejected_requests,
            COALESCE(SUM(CASE WHEN status = 'approved' THEN leave_days ELSE 0 END), 0) AS approved_leave_days
        FROM v_leave_requests
        WHERE {' AND '.join(where_parts)}
        GROUP BY department_id, department_name
        ORDER BY approved_leave_days DESC, department_name ASC
    """
    res = _exec_tool_sql(conn, sql, params)
    res["tool_name"] = "get_leave_by_department"
    return res


def get_top_late_employees(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    period: Optional[str] = "2026-10",
    limit: int = 5,
    department_name: Optional[str] = None,
) -> Dict[str, Any]:
    limit = max(1, min(int(limit), 50))
    scope_sql, params = build_scope_filter(user, "employee_id", "department_id")
    where_parts = [scope_sql, "is_late = 1"]
    if period:
        where_parts.append("period = ?")
        params.append(period)
    if department_name and user.role in (RoleEnum.hr, RoleEnum.executive):
        where_parts.append("LOWER(department_name) = LOWER(?)")
        params.append(department_name)

    sql = f"""
        SELECT
            employee_id,
            full_name,
            department_name,
            COUNT(*) AS late_days,
            SUM(late_minutes) AS total_late_minutes,
            ROUND(AVG(late_minutes), 1) AS avg_late_minutes
        FROM v_attendance_daily
        WHERE {' AND '.join(where_parts)}
        GROUP BY employee_id, full_name, department_name
        ORDER BY late_days DESC, total_late_minutes DESC
        LIMIT ?
    """
    params.append(limit)
    res = _exec_tool_sql(conn, sql, params)
    res["tool_name"] = "get_top_late_employees"
    return res


def get_leave_balance(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    threshold: Optional[float] = None,
    target_employee_id: Optional[str] = None,
) -> Dict[str, Any]:
    scope_sql, params = build_scope_filter(user, "e.employee_id", "e.department_id")
    where_parts = [scope_sql, "e.employment_status = 'active'"]
    if target_employee_id:
        where_parts.append("e.employee_id = ?")
        params.append(target_employee_id.upper())

    having_sql = ""
    if threshold is not None:
        having_sql = "HAVING (e.annual_leave_balance - COALESCE(SUM(CASE WHEN lr.leave_type = 'annual' AND lr.status = 'approved' THEN lr.leave_days ELSE 0 END), 0)) <= ?"
        params.append(float(threshold))

    sql = f"""
        SELECT
            e.employee_id,
            e.full_name,
            e.department_name,
            e.annual_leave_balance,
            COALESCE(SUM(CASE WHEN lr.leave_type = 'annual' AND lr.status = 'approved' THEN lr.leave_days ELSE 0 END), 0) AS used_annual_days,
            ROUND(
                e.annual_leave_balance - COALESCE(SUM(CASE WHEN lr.leave_type = 'annual' AND lr.status = 'approved' THEN lr.leave_days ELSE 0 END), 0),
                1
            ) AS remaining_annual_days
        FROM v_employees e
        LEFT JOIN v_leave_requests lr ON lr.employee_id = e.employee_id
        WHERE {' AND '.join(where_parts)}
        GROUP BY e.employee_id, e.full_name, e.department_name, e.annual_leave_balance
        {having_sql}
        ORDER BY remaining_annual_days ASC, e.employee_id ASC
        LIMIT 50
    """
    res = _exec_tool_sql(conn, sql, params)
    res["tool_name"] = "get_leave_balance"
    return res


def list_anomalies_tool(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    period: Optional[str] = None,
    severity: Optional[str] = None,
    rule_code: Optional[str] = None,
) -> Dict[str, Any]:
    if user.role in (RoleEnum.hr, RoleEnum.executive):
        scope_sql, params = "1 = 1", []
    elif user.role == RoleEnum.manager:
        scope_sql, params = "department_id = ?", [user.department_id]
    elif user.role == RoleEnum.employee:
        scope_sql, params = "scope_type = 'employee' AND employee_id = ?", [user.employee_id]
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Quản trị hệ thống (Admin) không có quyền truy vấn cảnh báo nghiệp vụ R1-R8.",
        )

    where_parts = [scope_sql]
    if period:
        where_parts.append("period = ?")
        params.append(period)
    if severity:
        where_parts.append("severity = ?")
        params.append(severity.lower())
    if rule_code:
        where_parts.append("rule_code = ?")
        params.append(rule_code.upper())

    sql = f"""
        SELECT
            anomaly_id,
            rule_code,
            anomaly_type,
            scope_type,
            COALESCE(employee_id, 'Cấp phòng') AS target_code,
            COALESCE(full_name, department_name) AS target_name,
            department_name,
            period,
            severity,
            review_status,
            explanation
        FROM v_anomalies
        WHERE {' AND '.join(where_parts)}
        ORDER BY CASE severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, period DESC, anomaly_id DESC
        LIMIT 50
    """
    res = _exec_tool_sql(conn, sql, params)
    res["tool_name"] = "list_anomalies"
    return res


def compare_department_metrics(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    period: str = "2026-10",
) -> Dict[str, Any]:
    scope_sql, params = build_scope_filter(user, "employee_id", "department_id")
    where_parts = [scope_sql, "period = ?"]
    params.append(period)

    sql = f"""
        SELECT
            department_id,
            department_name,
            COUNT(DISTINCT employee_id) AS employee_count,
            ROUND(COALESCE(SUM(work_hours), 0), 1) AS total_work_hours,
            SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) AS present_days,
            SUM(CASE WHEN is_late = 1 THEN 1 ELSE 0 END) AS late_days,
            SUM(CASE WHEN status = 'on_leave' THEN 1 ELSE 0 END) AS leave_days,
            ROUND(
                CASE WHEN SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) > 0
                     THEN SUM(CASE WHEN is_late = 1 THEN 1 ELSE 0 END) * 100.0 / SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END)
                     ELSE 0.0 END,
                2
            ) AS late_rate_pct
        FROM v_attendance_daily
        WHERE {' AND '.join(where_parts)}
        GROUP BY department_id, department_name
        ORDER BY late_rate_pct DESC, department_name ASC
    """
    res = _exec_tool_sql(conn, sql, params)
    res["tool_name"] = "compare_department_metrics"
    return res


def get_attendance_trend(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    months: int = 3,
) -> Dict[str, Any]:
    """Strategic multi-month attendance trend (RBAC-scoped; used by Executive, HR & Manager)."""
    months = max(1, min(int(months), 12))
    scope_sql, params = build_scope_filter(user, "employee_id", "department_id")
    sql = f"""
        SELECT
            period,
            COUNT(DISTINCT employee_id) AS employee_count,
            ROUND(COALESCE(SUM(work_hours), 0), 1) AS total_work_hours,
            SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) AS present_days,
            SUM(CASE WHEN is_late = 1 THEN 1 ELSE 0 END) AS late_days,
            SUM(CASE WHEN status = 'on_leave' THEN 1 ELSE 0 END) AS leave_days,
            SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) AS absent_days,
            ROUND(
                CASE WHEN SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) > 0
                     THEN SUM(CASE WHEN is_late = 1 THEN 1 ELSE 0 END) * 100.0 / SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END)
                     ELSE 0.0 END,
                2
            ) AS late_rate_pct
        FROM v_attendance_daily
        WHERE {scope_sql}
        GROUP BY period
        ORDER BY period DESC
        LIMIT ?
    """
    params.append(months)
    res = _exec_tool_sql(conn, sql, params)
    res["rows"] = list(reversed(res["rows"]))
    res["tool_name"] = "get_attendance_trend"
    return res


def get_anomalies_by_department(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    period: Optional[str] = None,
) -> Dict[str, Any]:
    """Rank departments by R1-R8 anomaly volume (RBAC-scoped; blocks Admin & Employee)."""
    if user.role in (RoleEnum.hr, RoleEnum.executive):
        scope_sql, params = "1 = 1", []
    elif user.role == RoleEnum.manager:
        scope_sql, params = "department_id = ?", [user.department_id]
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vai trò hiện tại không có quyền xem thống kê cảnh báo theo phòng ban.",
        )

    where_parts = [scope_sql]
    if period:
        where_parts.append("period = ?")
        params.append(period)

    sql = f"""
        SELECT
            department_id,
            department_name,
            COUNT(*) AS total_anomalies,
            SUM(CASE WHEN review_status = 'open' THEN 1 ELSE 0 END) AS open_anomalies,
            SUM(CASE WHEN severity = 'high' THEN 1 ELSE 0 END) AS high_anomalies,
            SUM(CASE WHEN severity = 'medium' THEN 1 ELSE 0 END) AS medium_anomalies
        FROM v_anomalies
        WHERE {' AND '.join(where_parts)}
        GROUP BY department_id, department_name
        ORDER BY total_anomalies DESC, high_anomalies DESC, department_name ASC
        LIMIT 20
    """
    res = _exec_tool_sql(conn, sql, params)
    res["tool_name"] = "get_anomalies_by_department"
    return res


def run_sql_readonly_tool(
    db_path: Optional[Path | str],
    user: AuthenticatedUser,
    sql: str,
) -> Dict[str, Any]:
    """Fallback guarded read-only SQL executor (never used as default when a named tool matches)."""
    rows, validated_sql, elapsed_ms = execute_guarded_sql(db_path=db_path, user=user, sql=sql)
    return {
        "tool_name": "run_sql_readonly",
        "rows": rows,
        "row_count": len(rows),
        "sql_text": validated_sql,
        "execution_ms": elapsed_ms,
    }
