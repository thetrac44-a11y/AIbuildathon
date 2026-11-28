from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.core.security import (
    AuthenticatedUser,
    build_ai_scope_filter,
    resolve_ai_effective_scope,
)
from app.services.metrics_service import compute_attendance_rates
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


def _append_period_clause(
    where_parts: List[str],
    params: List[Any],
    period: Optional[str] = None,
    periods: Optional[List[str]] = None,
    col: str = "period",
) -> None:
    if periods:
        placeholders = ", ".join("?" for _ in periods)
        where_parts.append(f"{col} IN ({placeholders})")
        params.extend(periods)
    elif period:
        where_parts.append(f"{col} = ?")
        params.append(period)


def _check_attendance_presence(
    conn: sqlite3.Connection,
    where_parts: List[str],
    params: List[Any],
) -> Dict[str, Any]:
    row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS total_rows,
            SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) AS present_days
        FROM v_attendance_daily
        WHERE {' AND '.join(where_parts)}
        """,
        params,
    ).fetchone()
    total_rows = int((row["total_rows"] if row else 0) or 0)
    present_days = int((row["present_days"] if row else 0) or 0)
    return {
        "has_attendance_data": total_rows > 0,
        "present_days_in_scope": present_days,
    }


# =============================================================================
# 1. EXISTING 9 CORE SQL TOOLS (UPGRADED WITH EffectiveScope + target_emp + dept)
# =============================================================================

def get_daily_attendance(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    work_date: str,
    department_name: Optional[str] = None,
    target_employee_id: Optional[str] = None,
    force_self: bool = False,
) -> Dict[str, Any]:
    """Fetch exact attendance rows for a specific calendar date (YYYY-MM-DD), strictly RBAC-scoped."""
    scope = resolve_ai_effective_scope(user)
    scope_sql, params = build_ai_scope_filter(user, "employee_id", "department_id", force_self=force_self)
    where_parts = [scope_sql, "work_date = ?"]
    params.append(work_date)
    if department_name and scope == "all" and not force_self:
        where_parts.append("LOWER(department_name) = LOWER(?)")
        params.append(department_name)
    if target_employee_id:
        where_parts.append("employee_id = ?")
        params.append(target_employee_id.upper())

    sql = f"""
        SELECT
            employee_id,
            full_name,
            department_name,
            work_date,
            check_in,
            check_out,
            status,
            late_minutes,
            work_hours
        FROM v_attendance_daily
        WHERE {' AND '.join(where_parts)}
        ORDER BY employee_id ASC
        LIMIT 50
    """
    res = _exec_tool_sql(conn, sql, params)
    res["tool_name"] = "get_daily_attendance"
    return res


def get_attendance_summary(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    period: Optional[str] = "2026-10",
    periods: Optional[List[str]] = None,
    department_name: Optional[str] = None,
    target_employee_id: Optional[str] = None,
    force_self: bool = False,
) -> Dict[str, Any]:
    """Compute attendance summary KPIs using canonical metrics_service formulas, strictly RBAC-scoped."""
    scope = resolve_ai_effective_scope(user)
    scope_sql, params = build_ai_scope_filter(user, "employee_id", "department_id", force_self=force_self)
    where_parts = [scope_sql]
    _append_period_clause(where_parts, params, period=period, periods=periods)
    if department_name and scope == "all" and not force_self:
        where_parts.append("LOWER(department_name) = LOWER(?)")
        params.append(department_name)
    if target_employee_id:
        where_parts.append("employee_id = ?")
        params.append(target_employee_id.upper())

    group_clause = "GROUP BY period" if not periods else ""
    period_select = "period," if not periods else "MIN(period) || '..' || MAX(period) AS period,"

    sql = f"""
        SELECT
            {period_select}
            COUNT(DISTINCT employee_id) AS employee_count,
            ROUND(COALESCE(SUM(work_hours), 0), 1) AS total_work_hours,
            SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) AS present_days,
            SUM(CASE WHEN is_late = 1 THEN 1 ELSE 0 END) AS late_days,
            SUM(CASE WHEN status = 'present' AND (check_in IS NULL OR check_out IS NULL) THEN 1 ELSE 0 END) AS missing_punch_days,
            SUM(CASE WHEN status = 'on_leave' THEN 1 ELSE 0 END) AS leave_days,
            SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) AS absent_days
        FROM v_attendance_daily
        WHERE {' AND '.join(where_parts)}
        {group_clause}
    """
    res = _exec_tool_sql(conn, sql, params)
    enriched: List[Dict[str, Any]] = []
    for r in res["rows"]:
        emp_cnt = int(r.get("employee_count") or 0)
        if emp_cnt == 0:
            continue
        p_d = int(r.get("present_days") or 0)
        l_d = int(r.get("late_days") or 0)
        lv_d = int(r.get("leave_days") or 0)
        ab_d = int(r.get("absent_days") or 0)
        rates = compute_attendance_rates(p_d, l_d, lv_d, ab_d)
        r["present_days"] = p_d
        r["on_time_days"] = rates["on_time_days"]
        r["on_time_rate_pct"] = rates["on_time_rate"]
        r["late_days"] = l_d
        r["late_rate_pct"] = rates["late_rate"]
        r["leave_days"] = lv_d
        r["leave_rate_pct"] = rates["leave_rate"]
        r["absent_days"] = ab_d
        r["missing_punch_days"] = int(r.get("missing_punch_days") or 0)
        r["total_work_hours"] = round(float(r.get("total_work_hours") or 0.0), 1)
        enriched.append(r)
    res["rows"] = enriched
    res["row_count"] = len(enriched)
    res["tool_name"] = "get_attendance_summary"
    return res


def get_leave_by_department(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    period: Optional[str] = None,
    department_name: Optional[str] = None,
    target_employee_id: Optional[str] = None,
    force_self: bool = False,
) -> Dict[str, Any]:
    scope = resolve_ai_effective_scope(user)
    scope_sql, params = build_ai_scope_filter(user, "employee_id", "department_id", force_self=force_self)
    where_parts = [scope_sql]
    if period:
        where_parts.append("period = ?")
        params.append(period)
    if department_name and scope == "all" and not force_self:
        where_parts.append("LOWER(department_name) = LOWER(?)")
        params.append(department_name)
    if target_employee_id:
        where_parts.append("employee_id = ?")
        params.append(target_employee_id.upper())

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
    periods: Optional[List[str]] = None,
    limit: int = 5,
    department_name: Optional[str] = None,
    target_employee_id: Optional[str] = None,
    force_self: bool = False,
) -> Dict[str, Any]:
    limit = max(1, min(int(limit), 50))
    scope = resolve_ai_effective_scope(user)
    scope_sql, base_params = build_ai_scope_filter(user, "employee_id", "department_id", force_self=force_self)
    base_where = [scope_sql]
    _append_period_clause(base_where, base_params, period=period, periods=periods)
    if department_name and scope == "all" and not force_self:
        base_where.append("LOWER(department_name) = LOWER(?)")
        base_params.append(department_name)
    if target_employee_id:
        base_where.append("employee_id = ?")
        base_params.append(target_employee_id.upper())

    where_parts = [*base_where, "is_late = 1"]
    params = [*base_params, limit]

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
        ORDER BY late_days DESC, total_late_minutes DESC, employee_id ASC
        LIMIT ?
    """
    res = _exec_tool_sql(conn, sql, params)
    if not res["rows"]:
        presence = _check_attendance_presence(conn, base_where, base_params)
        res["has_attendance_data"] = presence["has_attendance_data"]
        res["present_days_in_scope"] = presence["present_days_in_scope"]
    else:
        res["has_attendance_data"] = True
        res["present_days_in_scope"] = None
    res["tool_name"] = "get_top_late_employees"
    return res


def get_leave_balance(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    threshold: Optional[float] = None,
    target_employee_id: Optional[str] = None,
    department_name: Optional[str] = None,
    force_self: bool = False,
) -> Dict[str, Any]:
    scope = resolve_ai_effective_scope(user)
    scope_sql, params = build_ai_scope_filter(user, "e.employee_id", "e.department_id", force_self=force_self)
    where_parts = [scope_sql, "e.employment_status = 'active'"]
    if target_employee_id:
        where_parts.append("e.employee_id = ?")
        params.append(target_employee_id.upper())
    if department_name and scope == "all" and not force_self:
        where_parts.append("LOWER(e.department_name) = LOWER(?)")
        params.append(department_name)

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
    periods: Optional[List[str]] = None,
    severity: Optional[str] = None,
    rule_code: Optional[str] = None,
    department_name: Optional[str] = None,
    target_employee_id: Optional[str] = None,
    force_self: bool = False,
) -> Dict[str, Any]:
    scope = resolve_ai_effective_scope(user)
    if scope == "none":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản hiện tại không có quyền truy vấn cảnh báo nghiệp vụ R1-R8.",
        )
    if force_self or scope == "self":
        scope_sql, params = "scope_type = 'employee' AND employee_id = ?", [user.employee_id]
    elif scope == "department":
        scope_sql, params = "department_id = ?", [user.department_id]
    else:
        scope_sql, params = "1 = 1", []

    where_parts = [scope_sql]
    _append_period_clause(where_parts, params, period=period, periods=periods)
    if severity:
        where_parts.append("severity = ?")
        params.append(severity.lower())
    if rule_code:
        where_parts.append("rule_code = ?")
        params.append(rule_code.upper())
    if department_name and scope == "all" and not force_self:
        where_parts.append("LOWER(department_name) = LOWER(?)")
        params.append(department_name)
    if target_employee_id:
        where_parts.append("employee_id = ?")
        params.append(target_employee_id.upper())

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
    department_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    scope = resolve_ai_effective_scope(user)
    scope_sql, params = build_ai_scope_filter(user, "employee_id", "department_id")
    where_parts = [scope_sql, "period = ?"]
    params.append(period)
    if department_names and scope == "all":
        placeholders = ", ".join("LOWER(?)" for _ in department_names)
        where_parts.append(f"LOWER(department_name) IN ({placeholders})")
        params.extend(department_names)

    sql = f"""
        SELECT
            department_id,
            department_name,
            COUNT(DISTINCT employee_id) AS employee_count,
            ROUND(COALESCE(SUM(work_hours), 0), 1) AS total_work_hours,
            SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) AS present_days,
            SUM(CASE WHEN is_late = 1 THEN 1 ELSE 0 END) AS late_days,
            SUM(CASE WHEN status = 'on_leave' THEN 1 ELSE 0 END) AS leave_days,
            SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) AS absent_days
        FROM v_attendance_daily
        WHERE {' AND '.join(where_parts)}
        GROUP BY department_id, department_name
        ORDER BY department_name ASC
    """
    res = _exec_tool_sql(conn, sql, params)
    rows: List[Dict[str, Any]] = []
    for r in res["rows"]:
        p_d = int(r.get("present_days") or 0)
        l_d = int(r.get("late_days") or 0)
        lv_d = int(r.get("leave_days") or 0)
        ab_d = int(r.get("absent_days") or 0)
        rates = compute_attendance_rates(p_d, l_d, lv_d, ab_d)
        r["present_days"] = p_d
        r["late_days"] = l_d
        r["leave_days"] = lv_d
        r["absent_days"] = ab_d
        r["on_time_rate_pct"] = rates["on_time_rate"]
        r["late_rate_pct"] = rates["late_rate"]
        r["leave_rate_pct"] = rates["leave_rate"]
        r["total_work_hours"] = round(float(r.get("total_work_hours") or 0.0), 1)
        rows.append(r)
    rows.sort(key=lambda x: (-x["late_rate_pct"], x["department_name"]))
    res["rows"] = rows
    res["row_count"] = len(rows)
    res["tool_name"] = "compare_department_metrics"
    return res


def get_attendance_trend(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    months: int = 3,
    periods: Optional[List[str]] = None,
    department_name: Optional[str] = None,
    force_self: bool = False,
) -> Dict[str, Any]:
    """Strategic multi-month attendance trend (RBAC-scoped; aligned with metrics_service formulas)."""
    months = max(1, min(int(months), 12))
    scope = resolve_ai_effective_scope(user)
    scope_sql, params = build_ai_scope_filter(user, "employee_id", "department_id", force_self=force_self)
    where_parts = [scope_sql]
    if periods:
        _append_period_clause(where_parts, params, periods=periods)
    if department_name and scope == "all" and not force_self:
        where_parts.append("LOWER(department_name) = LOWER(?)")
        params.append(department_name)

    limit_val = len(periods) if periods else months
    sql = f"""
        SELECT
            period,
            COUNT(DISTINCT employee_id) AS employee_count,
            ROUND(COALESCE(SUM(work_hours), 0), 1) AS total_work_hours,
            SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) AS present_days,
            SUM(CASE WHEN is_late = 1 THEN 1 ELSE 0 END) AS late_days,
            SUM(CASE WHEN status = 'on_leave' THEN 1 ELSE 0 END) AS leave_days,
            SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) AS absent_days
        FROM v_attendance_daily
        WHERE {' AND '.join(where_parts)}
        GROUP BY period
        ORDER BY period DESC
        LIMIT ?
    """
    params.append(limit_val)
    res = _exec_tool_sql(conn, sql, params)
    enriched: List[Dict[str, Any]] = []
    for r in reversed(res["rows"]):
        p_d = int(r.get("present_days") or 0)
        l_d = int(r.get("late_days") or 0)
        lv_d = int(r.get("leave_days") or 0)
        ab_d = int(r.get("absent_days") or 0)
        rates = compute_attendance_rates(p_d, l_d, lv_d, ab_d)
        r["present_days"] = p_d
        r["late_days"] = l_d
        r["leave_days"] = lv_d
        r["absent_days"] = ab_d
        r["on_time_rate_pct"] = rates["on_time_rate"]
        r["late_rate_pct"] = rates["late_rate"]
        r["leave_rate_pct"] = rates["leave_rate"]
        r["total_work_hours"] = round(float(r.get("total_work_hours") or 0.0), 1)
        enriched.append(r)
    res["rows"] = enriched
    res["row_count"] = len(enriched)
    res["tool_name"] = "get_attendance_trend"
    return res


def get_anomalies_by_department(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    period: Optional[str] = None,
    department_name: Optional[str] = None,
    open_only: bool = False,
) -> Dict[str, Any]:
    """Rank departments by R1-R8 anomaly volume with per-rule breakdown (blocks Admin & Self-only scope)."""
    scope = resolve_ai_effective_scope(user)
    if scope == "all":
        scope_sql, params = "1 = 1", []
    elif scope == "department":
        scope_sql, params = "department_id = ?", [user.department_id]
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vai trò hoặc quyền hiện tại không cho phép xem thống kê cảnh báo theo phòng ban.",
        )

    where_parts = [scope_sql]
    if period:
        where_parts.append("period = ?")
        params.append(period)
    if department_name and scope == "all":
        where_parts.append("LOWER(department_name) = LOWER(?)")
        params.append(department_name)
    if open_only:
        where_parts.append("review_status = 'open'")

    where_str = " AND ".join(where_parts)
    order_expr = "open_anomalies DESC, high_anomalies DESC, total_anomalies DESC" if open_only else "total_anomalies DESC, high_anomalies DESC"
    sql = f"""
        SELECT
            department_id,
            department_name,
            COUNT(*) AS total_anomalies,
            SUM(CASE WHEN review_status = 'open' THEN 1 ELSE 0 END) AS open_anomalies,
            SUM(CASE WHEN severity = 'high' THEN 1 ELSE 0 END) AS high_anomalies,
            SUM(CASE WHEN severity = 'medium' THEN 1 ELSE 0 END) AS medium_anomalies,
            SUM(CASE WHEN severity = 'low' THEN 1 ELSE 0 END) AS low_anomalies
        FROM v_anomalies
        WHERE {where_str}
        GROUP BY department_id, department_name
        ORDER BY {order_expr}, department_name ASC
        LIMIT 20
    """
    res = _exec_tool_sql(conn, sql, params)

    # Dual-DB safe per-rule R1-R8 breakdown without SQLite-only GROUP_CONCAT
    rule_rows = conn.execute(
        f"""
        SELECT department_id, rule_code, COUNT(*) AS cnt
        FROM v_anomalies
        WHERE {where_str}
        GROUP BY department_id, rule_code
        ORDER BY department_id ASC, rule_code ASC
        """,
        params,
    ).fetchall()
    breakdown_map: Dict[str, List[str]] = {}
    for rr in rule_rows:
        breakdown_map.setdefault(str(rr["department_id"]), []).append(f"{rr['rule_code']} ({int(rr['cnt'])})")

    for r in res["rows"]:
        r["rule_breakdown"] = ", ".join(breakdown_map.get(str(r["department_id"]), [])) or "—"
    res["tool_name"] = "get_anomalies_by_department"
    return res


# =============================================================================
# 2. NEW PHASE 1 PARAMETERIZED SQL INTELLIGENCE TOOLS (7 TOOLS)
# =============================================================================

def resolve_employee_in_scope(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    employee_id: str,
) -> Optional[Dict[str, Any]]:
    """Verify whether an employee_id exists strictly within the user's authoritative AI RBAC scope."""
    scope_sql, params = build_ai_scope_filter(user, "employee_id", "department_id")
    row = conn.execute(
        f"""
        SELECT employee_id, full_name, department_id, department_name, position, role, employment_status
        FROM v_employees
        WHERE {scope_sql} AND employee_id = ?
        LIMIT 1
        """,
        [*params, employee_id.upper()],
    ).fetchone()
    return dict(row) if row else None


def get_employee_directory_summary(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    department_name: Optional[str] = None,
    target_employee_id: Optional[str] = None,
    force_self: bool = False,
) -> Dict[str, Any]:
    """Query active employees, managers, and position distribution from v_employees (strictly RBAC-scoped)."""
    scope = resolve_ai_effective_scope(user)
    scope_sql, params = build_ai_scope_filter(user, "employee_id", "department_id", force_self=force_self)
    where_parts = [scope_sql, "employment_status = 'active'"]
    if department_name and scope == "all" and not force_self:
        where_parts.append("LOWER(department_name) = LOWER(?)")
        params.append(department_name)
    if target_employee_id:
        where_parts.append("employee_id = ?")
        params.append(target_employee_id.upper())

    sql = f"""
        SELECT
            employee_id,
            full_name,
            department_id,
            department_name,
            position,
            manager_id,
            manager_name,
            start_date,
            annual_leave_balance,
            role
        FROM v_employees
        WHERE {' AND '.join(where_parts)}
        ORDER BY CASE role WHEN 'executive' THEN 1 WHEN 'hr' THEN 2 WHEN 'manager' THEN 3 ELSE 4 END, employee_id ASC
        LIMIT 100
    """
    res = _exec_tool_sql(conn, sql, params, max_rows=100)
    managers = [
        r for r in res["rows"]
        if r.get("role") == "manager" or "trưởng phòng" in str(r.get("position") or "").lower()
    ]
    positions_count: Dict[str, int] = {}
    for r in res["rows"]:
        pos = str(r.get("position") or "Khác")
        positions_count[pos] = positions_count.get(pos, 0) + 1
    res["managers"] = managers
    res["positions_summary"] = positions_count
    res["tool_name"] = "get_employee_directory_summary"
    return res


def get_employee_attendance_detail(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    period: Optional[str] = "2026-10",
    periods: Optional[List[str]] = None,
    target_employee_id: Optional[str] = None,
    department_name: Optional[str] = None,
    filter_type: str = "late",
    order_by: str = "date",
    limit: int = 31,
    force_self: bool = False,
) -> Dict[str, Any]:
    """Fetch individual attendance dates (e.g. exact late dates, top N longest late days, missing punches)."""
    limit = max(1, min(int(limit), 100))
    scope = resolve_ai_effective_scope(user)
    scope_sql, base_params = build_ai_scope_filter(user, "employee_id", "department_id", force_self=force_self)
    base_where = [scope_sql]
    _append_period_clause(base_where, base_params, period=period, periods=periods)
    if department_name and scope == "all" and not force_self:
        base_where.append("LOWER(department_name) = LOWER(?)")
        base_params.append(department_name)
    if target_employee_id:
        base_where.append("employee_id = ?")
        base_params.append(target_employee_id.upper())

    where_parts = [*base_where]
    if filter_type == "late":
        where_parts.append("is_late = 1")
    elif filter_type == "missing_punch":
        where_parts.append("status = 'present' AND (check_in IS NULL OR check_out IS NULL)")
    elif filter_type == "absent":
        where_parts.append("status = 'absent'")
    elif filter_type == "on_leave":
        where_parts.append("status = 'on_leave'")

    if order_by == "late_minutes_desc":
        order_sql = "late_minutes DESC, work_date ASC"
    elif order_by == "work_hours_asc":
        order_sql = "work_hours ASC, work_date ASC"
    else:
        order_sql = "work_date ASC, employee_id ASC"

    sql = f"""
        SELECT
            work_date,
            employee_id,
            full_name,
            department_name,
            check_in,
            check_out,
            status,
            late_minutes,
            work_hours
        FROM v_attendance_daily
        WHERE {' AND '.join(where_parts)}
        ORDER BY {order_sql}
        LIMIT ?
    """
    res = _exec_tool_sql(conn, sql, [*base_params, limit], max_rows=limit)
    if not res["rows"]:
        presence = _check_attendance_presence(conn, base_where, base_params)
        res["has_attendance_data"] = presence["has_attendance_data"]
        res["present_days_in_scope"] = presence["present_days_in_scope"]
    else:
        res["has_attendance_data"] = True
        res["present_days_in_scope"] = None
    res["tool_name"] = "get_employee_attendance_detail"
    return res


def list_leave_requests_detail(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    period: Optional[str] = None,
    status_filter: Optional[str] = None,
    leave_type: Optional[str] = None,
    department_name: Optional[str] = None,
    target_employee_id: Optional[str] = None,
    requires_executive_approval: Optional[bool] = None,
    force_self: bool = False,
    limit: int = 50,
) -> Dict[str, Any]:
    """List individual leave requests (pending, approved, rejected, or executive-approval queue)."""
    limit = max(1, min(int(limit), 100))
    scope = resolve_ai_effective_scope(user)
    scope_sql, params = build_ai_scope_filter(user, "employee_id", "department_id", force_self=force_self)
    where_parts = [scope_sql]
    if period:
        where_parts.append("period = ?")
        params.append(period)
    if status_filter:
        where_parts.append("status = ?")
        params.append(status_filter.lower())
    if leave_type:
        where_parts.append("leave_type = ?")
        params.append(leave_type.lower())
    if department_name and scope == "all" and not force_self:
        where_parts.append("LOWER(department_name) = LOWER(?)")
        params.append(department_name)
    if target_employee_id:
        where_parts.append("employee_id = ?")
        params.append(target_employee_id.upper())
    if requires_executive_approval is not None:
        where_parts.append("requires_executive_approval = ?")
        params.append(1 if requires_executive_approval else 0)

    sql = f"""
        SELECT
            request_id,
            employee_id,
            full_name,
            department_name,
            leave_type,
            from_date,
            to_date,
            leave_days,
            status,
            requires_executive_approval,
            reason,
            decision_note
        FROM v_leave_requests
        WHERE {' AND '.join(where_parts)}
        ORDER BY from_date DESC, request_id DESC
        LIMIT ?
    """
    params.append(limit)
    res = _exec_tool_sql(conn, sql, params, max_rows=limit)
    res["tool_name"] = "list_leave_requests_detail"
    return res


def compare_periods(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    period_a: str,
    period_b: str,
    department_name: Optional[str] = None,
    target_employee_id: Optional[str] = None,
    force_self: bool = False,
) -> Dict[str, Any]:
    """Compare attendance KPIs side-by-side between two explicit periods (e.g. 2026-09 vs 2026-10)."""
    p_first, p_second = sorted([period_a, period_b])
    scope = resolve_ai_effective_scope(user)
    scope_sql, params = build_ai_scope_filter(user, "employee_id", "department_id", force_self=force_self)
    where_parts = [scope_sql, "period IN (?, ?)"]
    params.extend([p_first, p_second])
    if department_name and scope == "all" and not force_self:
        where_parts.append("LOWER(department_name) = LOWER(?)")
        params.append(department_name)
    if target_employee_id:
        where_parts.append("employee_id = ?")
        params.append(target_employee_id.upper())

    sql = f"""
        SELECT
            period,
            COUNT(DISTINCT employee_id) AS employee_count,
            ROUND(COALESCE(SUM(work_hours), 0), 1) AS total_work_hours,
            SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) AS present_days,
            SUM(CASE WHEN is_late = 1 THEN 1 ELSE 0 END) AS late_days,
            SUM(CASE WHEN status = 'on_leave' THEN 1 ELSE 0 END) AS leave_days,
            SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) AS absent_days
        FROM v_attendance_daily
        WHERE {' AND '.join(where_parts)}
        GROUP BY period
        ORDER BY period ASC
    """
    res = _exec_tool_sql(conn, sql, params)
    rows: List[Dict[str, Any]] = []
    for r in res["rows"]:
        p_d = int(r.get("present_days") or 0)
        l_d = int(r.get("late_days") or 0)
        lv_d = int(r.get("leave_days") or 0)
        ab_d = int(r.get("absent_days") or 0)
        rates = compute_attendance_rates(p_d, l_d, lv_d, ab_d)
        r["present_days"] = p_d
        r["late_days"] = l_d
        r["leave_days"] = lv_d
        r["absent_days"] = ab_d
        r["on_time_rate_pct"] = rates["on_time_rate"]
        r["late_rate_pct"] = rates["late_rate"]
        r["leave_rate_pct"] = rates["leave_rate"]
        r["total_work_hours"] = round(float(r.get("total_work_hours") or 0.0), 1)
        rows.append(r)
    res["rows"] = rows
    res["row_count"] = len(rows)
    res["tool_name"] = "compare_periods"
    return res


def compare_departments_full(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    period: str = "2026-10",
    department_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Comprehensive Executive/HR department comparison uniting attendance KPIs (metrics_service) & R1-R8 anomalies."""
    base = compare_department_metrics(conn, user, period=period, department_names=department_names)
    scope = resolve_ai_effective_scope(user)

    anom_where = ["period = ?"]
    anom_params: List[Any] = [period]
    if scope == "department":
        anom_where.append("department_id = ?")
        anom_params.append(user.department_id)
    elif scope == "self":
        anom_where.append("scope_type = 'employee' AND employee_id = ?")
        anom_params.append(user.employee_id)
    elif department_names and scope == "all":
        placeholders = ", ".join("LOWER(?)" for _ in department_names)
        anom_where.append(f"LOWER(department_name) IN ({placeholders})")
        anom_params.extend(department_names)

    anom_rows = conn.execute(
        f"""
        SELECT
            department_id,
            COUNT(*) AS total_anomalies,
            SUM(CASE WHEN review_status = 'open' THEN 1 ELSE 0 END) AS open_anomalies,
            SUM(CASE WHEN severity = 'high' THEN 1 ELSE 0 END) AS high_anomalies
        FROM v_anomalies
        WHERE {' AND '.join(anom_where)}
        GROUP BY department_id
        """,
        anom_params,
    ).fetchall()
    anom_map = {
        str(r["department_id"]): {
            "total_anomalies": int(r["total_anomalies"] or 0),
            "open_anomalies": int(r["open_anomalies"] or 0),
            "high_anomalies": int(r["high_anomalies"] or 0),
        }
        for r in anom_rows
    }

    for r in base["rows"]:
        info = anom_map.get(str(r["department_id"]), {"total_anomalies": 0, "open_anomalies": 0, "high_anomalies": 0})
        r["total_anomalies"] = info["total_anomalies"]
        r["open_anomalies"] = info["open_anomalies"]
        r["high_anomalies"] = info["high_anomalies"]

    base["tool_name"] = "compare_departments_full"
    return base


def list_holidays_and_overtime(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    period: Optional[str] = None,
    target_employee_id: Optional[str] = None,
    department_name: Optional[str] = None,
    force_self: bool = False,
) -> Dict[str, Any]:
    """Fetch public company holidays and strictly RBAC-scoped overtime requests."""
    scope = resolve_ai_effective_scope(user)
    scope_sql, ot_params = build_ai_scope_filter(user, "e.employee_id", "e.department_id", force_self=force_self)
    ot_where = [scope_sql]
    if period:
        ot_where.append("SUBSTR(CAST(o.work_date AS TEXT), 1, 7) = ?")
        ot_params.append(period)
    if department_name and scope == "all" and not force_self:
        ot_where.append("LOWER(e.department_name) = LOWER(?)")
        ot_params.append(department_name)
    if target_employee_id:
        ot_where.append("e.employee_id = ?")
        ot_params.append(target_employee_id.upper())

    holidays_rows = [
        dict(r)
        for r in conn.execute("SELECT holiday_date, name FROM holidays ORDER BY holiday_date ASC").fetchall()
    ]
    ot_sql = f"""
        SELECT
            o.id,
            o.employee_id,
            e.full_name,
            e.department_name,
            o.work_date,
            o.status,
            o.approved_by
        FROM overtime_requests o
        JOIN v_employees e ON e.employee_id = o.employee_id
        WHERE {' AND '.join(ot_where)}
        ORDER BY o.work_date DESC, o.id DESC
        LIMIT 50
    """
    res = _exec_tool_sql(conn, ot_sql, ot_params, max_rows=50)
    res["holidays"] = holidays_rows
    res["tool_name"] = "list_holidays_and_overtime"
    return res


def run_sql_readonly_tool(
    db_path: Optional[Path | str],
    user: AuthenticatedUser,
    sql: str,
) -> Dict[str, Any]:
    """Fallback guarded read-only SQL executor protected by SQL Guard v2 (AST + RBAC TEMP views)."""
    rows, validated_sql, elapsed_ms = execute_guarded_sql(db_path=db_path, user=user, sql=sql)
    return {
        "tool_name": "run_sql_readonly",
        "rows": rows,
        "row_count": len(rows),
        "sql_text": validated_sql,
        "execution_ms": elapsed_ms,
    }
