from __future__ import annotations

import sqlite3
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.config import settings
from app.core.security import (
    AuthenticatedUser,
    assert_department_access,
    assert_employee_access,
    build_scope_filter,
    get_current_user,
    get_db_dependency,
    hash_password,
    require_permissions,
    sync_user_role_mapping,
    write_activity_log,
)
from app.schemas.auth import (
    AccountCreateRequest,
    AccountUpdateRequest,
    EmployeeCreateRequest,
    EmployeeUpdateRequest,
)
from app.schemas.common import RoleEnum
from app.services.metrics_service import compute_attendance_rates

router = APIRouter(prefix="/api", tags=["dashboard-and-admin"])

PRIVILEGED_SYSTEM_ROLES = {RoleEnum.admin.value, RoleEnum.executive.value}
TECHNICAL_AUDIT_ACTIONS = ("update_system_config", "update_role_permissions", "manage_kiosk_device")


def _count_active_accounts_by_role(
    conn: sqlite3.Connection,
    role_code: str,
    exclude_user_id: Optional[str] = None,
) -> int:
    sql = """
        SELECT COUNT(*)
        FROM users u
        JOIN employees e ON e.employee_id = u.employee_id
        WHERE e.role = ? AND u.is_active = 1 AND e.employment_status = 'active'
    """
    params: List[Any] = [role_code]
    if exclude_user_id:
        sql += " AND u.user_id != ?"
        params.append(exclude_user_id)
    return int(conn.execute(sql, params).fetchone()[0])


# =============================================================================
# 1. DASHBOARD SUMMARY (5-ROLE RBAC-SCOPED; ADMIN BLOCKED FROM HR BUSINESS DATA)
# =============================================================================

@router.get("/dashboard/summary")
def get_dashboard_summary(
    period: str = Query(default="2026-10", pattern=r"^\d{4}-\d{2}$"),
    department_id: Optional[str] = Query(default=None),
    current_user: AuthenticatedUser = Depends(
        require_permissions("dashboard.self", "dashboard.department", "dashboard.all", "dashboard.executive")
    ),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    effective_dept = assert_department_access(current_user, department_id)
    scope_sql, scope_params = build_scope_filter(current_user, "employee_id", "department_id")
    is_company_scope = current_user.role in (RoleEnum.hr, RoleEnum.executive)

    where_clauses = [scope_sql, "period = ?"]
    params: List[Any] = [*scope_params, period]
    if effective_dept and is_company_scope:
        where_clauses.append("department_id = ?")
        params.append(effective_dept)
    where_str = " AND ".join(where_clauses)

    # Employee count in scope
    emp_where, emp_params = build_scope_filter(current_user, "employee_id", "department_id")
    if effective_dept and is_company_scope:
        emp_where = f"{emp_where} AND department_id = ?"
        emp_params = [*emp_params, effective_dept]

    total_employees = conn.execute(
        f"SELECT COUNT(*) FROM employees WHERE employment_status = 'active' AND {emp_where}",
        emp_params,
    ).fetchone()[0]

    att_row = conn.execute(
        f"""
        SELECT
            COALESCE(SUM(work_hours), 0) AS total_work_hours,
            SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) AS present_days,
            SUM(CASE WHEN is_late = 1 THEN 1 ELSE 0 END) AS late_days,
            SUM(CASE WHEN status = 'on_leave' THEN 1 ELSE 0 END) AS leave_days,
            SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) AS absent_days,
            SUM(CASE WHEN status = 'present' AND (check_in IS NULL OR check_out IS NULL) THEN 1 ELSE 0 END) AS missing_punch_days
        FROM v_attendance_daily
        WHERE {where_str}
        """,
        params,
    ).fetchone()

    present_days = int(att_row["present_days"] or 0)
    late_days = int(att_row["late_days"] or 0)
    leave_days = int(att_row["leave_days"] or 0)
    absent_days = int(att_row["absent_days"] or 0)
    total_work_hours = round(float(att_row["total_work_hours"] or 0.0), 1)
    overall_rates = compute_attendance_rates(present_days, late_days, leave_days, absent_days)
    late_rate = overall_rates["late_rate"]
    on_time_days = overall_rates["on_time_days"]
    on_time_rate = overall_rates["on_time_rate"]
    leave_rate = overall_rates["leave_rate"]

    # Pending leaves in scope: distinguish active pending queue (all periods) vs period-specific pending
    pending_leaves = conn.execute(
        f"SELECT COUNT(*) FROM v_leave_requests WHERE {emp_where} AND status = 'pending'",
        emp_params,
    ).fetchone()[0]
    pending_leaves_in_period = conn.execute(
        f"SELECT COUNT(*) FROM v_leave_requests WHERE {emp_where} AND status = 'pending' AND period = ?",
        [*emp_params, period],
    ).fetchone()[0]
    executive_pending_leaves = conn.execute(
        f"SELECT COUNT(*) FROM v_leave_requests WHERE {emp_where} AND status = 'pending' AND requires_executive_approval = 1",
        emp_params,
    ).fetchone()[0]

    # Open anomalies in scope (explicitly enforce scope_type='employee' for Employee role)
    if current_user.role == RoleEnum.employee:
        anom_where_clauses = ["scope_type = 'employee'", "employee_id = ?", "period = ?", "review_status = 'open'"]
        anom_params: List[Any] = [current_user.employee_id, period]
    elif current_user.role == RoleEnum.manager:
        anom_where_clauses = ["department_id = ?", "period = ?", "review_status = 'open'"]
        anom_params = [current_user.department_id, period]
    else:
        anom_where_clauses = ["1 = 1", "period = ?", "review_status = 'open'"]
        anom_params = [period]
        if effective_dept:
            anom_where_clauses.append("department_id = ?")
            anom_params.append(effective_dept)
    anom_where_str = " AND ".join(anom_where_clauses)

    open_anomalies = conn.execute(
        f"SELECT COUNT(*) FROM v_anomalies WHERE {anom_where_str}",
        anom_params,
    ).fetchone()[0]

    high_anomalies = conn.execute(
        f"SELECT COUNT(*) FROM v_anomalies WHERE {anom_where_str} AND severity = 'high'",
        anom_params,
    ).fetchone()[0]

    # Anomaly counts by department (for Executive/HR department comparison)
    dept_anom_map: Dict[str, Dict[str, int]] = {}
    if current_user.role != RoleEnum.employee:
        dept_anom_where = ["period = ?"]
        dept_anom_params: List[Any] = [period]
        if current_user.role == RoleEnum.manager:
            dept_anom_where.append("department_id = ?")
            dept_anom_params.append(current_user.department_id)
        elif effective_dept:
            dept_anom_where.append("department_id = ?")
            dept_anom_params.append(effective_dept)
        for ar in conn.execute(
            f"""
            SELECT department_id,
                   COUNT(*) AS total_anomalies,
                   SUM(CASE WHEN review_status = 'open' THEN 1 ELSE 0 END) AS open_anomalies
            FROM v_anomalies
            WHERE {' AND '.join(dept_anom_where)}
            GROUP BY department_id
            """,
            dept_anom_params,
        ).fetchall():
            dept_anom_map[ar["department_id"]] = {
                "total_anomalies": int(ar["total_anomalies"] or 0),
                "open_anomalies": int(ar["open_anomalies"] or 0),
            }

    # Department breakdown (only departments in scope, using shared metrics_service formulas)
    dept_breakdown_rows = conn.execute(
        f"""
        SELECT
            department_id,
            department_name,
            COUNT(DISTINCT employee_id) AS employee_count,
            SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) AS present_days,
            SUM(CASE WHEN is_late = 1 THEN 1 ELSE 0 END) AS late_days,
            SUM(CASE WHEN status = 'on_leave' THEN 1 ELSE 0 END) AS leave_days,
            SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) AS absent_days
        FROM v_attendance_daily
        WHERE {where_str}
        GROUP BY department_id, department_name
        ORDER BY department_name
        """,
        params,
    ).fetchall()

    department_chart = []
    for r in dept_breakdown_rows:
        p_d = int(r["present_days"] or 0)
        l_d = int(r["late_days"] or 0)
        lv_d = int(r["leave_days"] or 0)
        ab_d = int(r["absent_days"] or 0)
        dept_rates = compute_attendance_rates(p_d, l_d, lv_d, ab_d)
        anom_info = dept_anom_map.get(r["department_id"], {"total_anomalies": 0, "open_anomalies": 0})
        department_chart.append(
            {
                "department_id": r["department_id"],
                "department_name": r["department_name"],
                "employee_count": int(r["employee_count"]),
                "present_days": p_d,
                "late_days": l_d,
                "leave_days": lv_d,
                "absent_days": ab_d,
                "leave_rate": dept_rates["leave_rate"],
                "late_rate": dept_rates["late_rate"],
                "on_time_rate": dept_rates["on_time_rate"],
                "total_anomalies": anom_info["total_anomalies"],
                "open_anomalies": anom_info["open_anomalies"],
            }
        )

    # Monthly attendance trend (used for Executive/HR/Manager trend analytics)
    trend_where = [scope_sql]
    trend_params: List[Any] = [*scope_params]
    if effective_dept and is_company_scope:
        trend_where.append("department_id = ?")
        trend_params.append(effective_dept)
    trend_rows = conn.execute(
        f"""
        SELECT
            period,
            SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) AS present_days,
            SUM(CASE WHEN is_late = 1 THEN 1 ELSE 0 END) AS late_days,
            SUM(CASE WHEN status = 'on_leave' THEN 1 ELSE 0 END) AS leave_days,
            SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END) AS absent_days
        FROM v_attendance_daily
        WHERE {' AND '.join(trend_where)}
        GROUP BY period
        ORDER BY period ASC
        """,
        trend_params,
    ).fetchall()
    monthly_trend = []
    for tr in trend_rows:
        tp = int(tr["present_days"] or 0)
        tl = int(tr["late_days"] or 0)
        tlv = int(tr["leave_days"] or 0)
        tab = int(tr["absent_days"] or 0)
        t_rates = compute_attendance_rates(tp, tl, tlv, tab)
        monthly_trend.append(
            {
                "period": tr["period"],
                "present_days": tp,
                "late_days": tl,
                "leave_days": tlv,
                "absent_days": tab,
                "late_rate": t_rates["late_rate"],
                "on_time_rate": t_rates["on_time_rate"],
                "leave_rate": t_rates["leave_rate"],
            }
        )

    # Personal leave remaining for Employee dashboard
    used_annual = conn.execute(
        """
        SELECT COALESCE(SUM(leave_days), 0)
        FROM v_leave_requests
        WHERE employee_id = ? AND leave_type = 'annual' AND status = 'approved'
        """,
        (current_user.employee_id,),
    ).fetchone()[0]
    remaining_annual_leave = max(0.0, round(current_user.annual_leave_balance - float(used_annual or 0), 1))

    # Top open alerts in scope
    top_alerts = [
        dict(r)
        for r in conn.execute(
            f"""
            SELECT anomaly_id, employee_id, full_name, department_name, scope_type, rule_code, anomaly_type, severity, review_status
            FROM v_anomalies
            WHERE {anom_where_str}
            ORDER BY CASE severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, anomaly_id DESC
            LIMIT 5
            """,
            anom_params,
        ).fetchall()
    ]

    # Personal daily calendar for Employee
    calendar_days = []
    if current_user.role == RoleEnum.employee:
        cal_rows = conn.execute(
            """
            SELECT work_date, status, is_late, late_minutes, work_hours, check_in, check_out
            FROM v_attendance_daily
            WHERE employee_id = ? AND period = ?
            ORDER BY work_date
            """,
            (current_user.employee_id, period),
        ).fetchall()
        calendar_days = [dict(r) for r in cal_rows]

    return {
        "period": period,
        "role": current_user.role.value,
        "scope": {
            "employee_id": current_user.employee_id if current_user.role == RoleEnum.employee else None,
            "department_id": effective_dept,
        },
        "kpis": {
            "total_employees": int(total_employees),
            "total_work_hours": total_work_hours,
            "present_days": present_days,
            "on_time_days": on_time_days,
            "on_time_rate": on_time_rate,
            "late_days": late_days,
            "late_rate": late_rate,
            "leave_days": leave_days,
            "leave_rate": leave_rate,
            "absent_days": absent_days,
            "missing_punch_days": int(att_row["missing_punch_days"] or 0),
            "pending_leaves": int(pending_leaves),
            "pending_leaves_in_period": int(pending_leaves_in_period),
            "executive_pending_leaves": int(executive_pending_leaves),
            "open_anomalies": int(open_anomalies),
            "high_anomalies": int(high_anomalies),
            "remaining_annual_leave": remaining_annual_leave,
        },
        "status_distribution": [
            {"name": "Đúng giờ", "value": on_time_days},
            {"name": "Đi muộn", "value": late_days},
            {"name": "Nghỉ phép", "value": leave_days},
            {"name": "Vắng", "value": absent_days},
        ],
        "department_chart": department_chart,
        "monthly_trend": monthly_trend,
        "top_alerts": top_alerts,
        "calendar_days": calendar_days,
    }


# =============================================================================
# 2. DEPARTMENTS & EMPLOYEES MANAGEMENT (HR CRUD, MANAGER/EXECUTIVE READ-ONLY)
# =============================================================================

@router.get("/departments")
def list_departments(
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db_dependency),
):
    if current_user.role in (RoleEnum.hr, RoleEnum.executive):
        rows = conn.execute("SELECT department_id, name FROM departments ORDER BY name").fetchall()
    elif current_user.role in (RoleEnum.manager, RoleEnum.employee):
        rows = conn.execute(
            "SELECT department_id, name FROM departments WHERE department_id = ?",
            (current_user.department_id,),
        ).fetchall()
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Quản trị hệ thống (Admin) không mặc định truy cập danh mục nghiệp vụ phòng ban.",
        )
    return {"items": [dict(r) for r in rows]}


@router.get("/employees")
def list_employees(
    search: Optional[str] = Query(default=None),
    department_id: Optional[str] = Query(default=None),
    employment_status: Optional[str] = Query(default=None),
    current_user: AuthenticatedUser = Depends(
        require_permissions("employee.read.department", "employee.read.all", "employee.manage")
    ),
    conn: sqlite3.Connection = Depends(get_db_dependency),
):
    if current_user.role == RoleEnum.manager and not settings.allow_manager_employee_read:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chức năng xem danh sách nhân viên không bật cho Trưởng phòng.",
        )

    effective_dept = assert_department_access(current_user, department_id)
    where_clauses = ["1 = 1"]
    params: List[Any] = []

    if effective_dept:
        where_clauses.append("e.department_id = ?")
        params.append(effective_dept)
    if employment_status and employment_status != "all":
        where_clauses.append("e.employment_status = ?")
        params.append(employment_status)
    if search:
        like = f"%{search.strip()}%"
        where_clauses.append("(e.employee_id LIKE ? OR e.full_name LIKE ? OR e.position LIKE ?)")
        params.extend([like, like, like])

    rows = conn.execute(
        f"""
        SELECT
            e.employee_id,
            e.full_name,
            e.department_id,
            d.name AS department_name,
            e.position,
            e.manager_id,
            m.full_name AS manager_name,
            e.start_date,
            e.annual_leave_balance,
            e.role,
            e.employment_status,
            e.email,
            e.phone,
            COALESCE((
                SELECT SUM(lr.leave_days)
                FROM v_leave_requests lr
                WHERE lr.employee_id = e.employee_id
                  AND lr.leave_type = 'annual'
                  AND lr.status = 'approved'
            ), 0) AS used_annual_leave
        FROM employees e
        JOIN departments d ON d.department_id = e.department_id
        LEFT JOIN employees m ON m.employee_id = e.manager_id
        WHERE {' AND '.join(where_clauses)}
        ORDER BY e.employee_id
        """,
        params,
    ).fetchall()

    items = []
    for r in rows:
        item = dict(r)
        item["remaining_annual_leave"] = max(
            0.0, round(float(item["annual_leave_balance"]) - float(item["used_annual_leave"] or 0), 1)
        )
        items.append(item)
    return {"total": len(items), "can_edit": current_user.has_permission("employee.manage"), "items": items}


@router.get("/employees/{employee_id}")
def get_employee_detail(
    employee_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db_dependency),
):
    assert_employee_access(conn, current_user, employee_id)
    row = conn.execute(
        """
        SELECT
            e.employee_id, e.full_name, e.department_id, d.name AS department_name,
            e.position, e.manager_id, m.full_name AS manager_name,
            e.start_date, e.annual_leave_balance, e.role, e.employment_status, e.email, e.phone
        FROM employees e
        JOIN departments d ON d.department_id = e.department_id
        LEFT JOIN employees m ON m.employee_id = e.manager_id
        WHERE e.employee_id = ?
        """,
        (employee_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy nhân viên.")
    return dict(row)


@router.post("/employees", status_code=status.HTTP_201_CREATED)
def create_employee(
    payload: EmployeeCreateRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("employee.manage")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
):
    # HR MUST NOT create admin or executive roles (only Admin can assign privileged system/executive roles)
    if payload.role.value in PRIVILEGED_SYSTEM_ROLES and not current_user.has_permission("role.manage"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nhân sự (HR) không được phép gán vai trò Quản trị hệ thống (admin) hoặc Cấp lãnh đạo (executive).",
        )

    emp_id = payload.employee_id.strip().upper()
    exists = conn.execute("SELECT 1 FROM employees WHERE employee_id = ?", (emp_id,)).fetchone()
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Mã nhân viên {emp_id} đã tồn tại.")

    dept = conn.execute("SELECT 1 FROM departments WHERE department_id = ?", (payload.department_id,)).fetchone()
    if not dept:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Phòng ban không hợp lệ.")

    if payload.manager_id:
        mgr = conn.execute("SELECT 1 FROM employees WHERE employee_id = ?", (payload.manager_id,)).fetchone()
        if not mgr:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quản lý trực tiếp không tồn tại.")

    email = payload.email.strip().lower() if payload.email else f"{emp_id.lower()}@company.vn"
    conn.execute(
        """
        INSERT INTO employees (
            employee_id, full_name, department_id, position, manager_id,
            start_date, annual_leave_balance, role, employment_status, email, phone
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
        """,
        (
            emp_id,
            payload.full_name.strip(),
            payload.department_id,
            payload.position.strip(),
            payload.manager_id,
            payload.start_date,
            payload.annual_leave_balance,
            payload.role.value,
            email,
            payload.phone,
        ),
    )
    write_activity_log(
        conn,
        actor_user_id=current_user.user_id,
        action="create_employee",
        entity_type="employee",
        entity_id=emp_id,
        after_obj=payload.model_dump(mode="json"),
    )
    conn.commit()
    return {"status": "ok", "employee_id": emp_id}


@router.patch("/employees/{employee_id}")
def update_employee(
    employee_id: str,
    payload: EmployeeUpdateRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("employee.manage")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
):
    existing = conn.execute("SELECT * FROM employees WHERE employee_id = ?", (employee_id,)).fetchone()
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy nhân viên.")

    before_dict = dict(existing)
    updates = payload.model_dump(exclude_unset=True, mode="json")
    if not updates:
        return {"status": "ok", "employee_id": employee_id}

    # HR cannot modify admin/executive role or escalate any employee to admin/executive
    if not current_user.has_permission("role.manage"):
        if "role" in updates and updates["role"] in PRIVILEGED_SYSTEM_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Nhân sự (HR) không có quyền nâng quyền lên vai trò Admin hoặc Executive.",
            )
        if before_dict["role"] in PRIVILEGED_SYSTEM_ROLES and ("role" in updates or "employment_status" in updates):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Nhân sự (HR) không có quyền thay đổi vai trò hoặc trạng thái tài khoản Admin/Executive.",
            )

    linked_user = conn.execute(
        "SELECT user_id, is_active FROM users WHERE employee_id = ?",
        (employee_id,),
    ).fetchone()

    # Protect the last active Admin and last active HR account
    if linked_user and linked_user["is_active"] == 1:
        for protected_role, label in [("admin", "Quản trị viên (Admin)"), ("hr", "HR")]:
            if before_dict["role"] == protected_role:
                demoting = "role" in updates and updates["role"] != protected_role
                deactivating = "employment_status" in updates and updates["employment_status"] != "active"
                if (demoting or deactivating) and _count_active_accounts_by_role(
                    conn, protected_role, exclude_user_id=linked_user["user_id"]
                ) == 0:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Không thể hạ quyền hoặc ngừng hoạt động tài khoản {label} cuối cùng còn hoạt động.",
                    )

    if "department_id" in updates:
        dept = conn.execute("SELECT 1 FROM departments WHERE department_id = ?", (updates["department_id"],)).fetchone()
        if not dept:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Phòng ban không hợp lệ.")

    if "manager_id" in updates and updates["manager_id"]:
        if updates["manager_id"] == employee_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nhân viên không thể tự quản lý chính mình.")
        mgr = conn.execute("SELECT 1 FROM employees WHERE employee_id = ?", (updates["manager_id"],)).fetchone()
        if not mgr:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quản lý trực tiếp không tồn tại.")

    set_clauses = [f"{col} = ?" for col in updates.keys()]
    values = list(updates.values()) + [employee_id]
    conn.execute(f"UPDATE employees SET {', '.join(set_clauses)} WHERE employee_id = ?", values)

    if "role" in updates and linked_user:
        sync_user_role_mapping(conn, linked_user["user_id"], updates["role"], assigned_by_user_id=current_user.user_id)

    after_row = conn.execute("SELECT * FROM employees WHERE employee_id = ?", (employee_id,)).fetchone()
    write_activity_log(
        conn,
        actor_user_id=current_user.user_id,
        action="update_employee",
        entity_type="employee",
        entity_id=employee_id,
        before_obj=before_dict,
        after_obj=dict(after_row),
    )
    conn.commit()
    return {"status": "ok", "employee": dict(after_row)}


# =============================================================================
# 3. ACCOUNTS MANAGEMENT (ADMIN FULL 5-ROLE + LAST-ADMIN PROTECTION; HR SCOPED)
# =============================================================================

@router.get("/accounts")
def list_accounts(
    search: Optional[str] = Query(default=None),
    role: Optional[str] = Query(default=None),
    current_user: AuthenticatedUser = Depends(require_permissions("account.manage", "account.manage.business")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
):
    is_system_admin = current_user.has_permission("account.manage")
    where_clauses = ["1 = 1"]
    params: List[Any] = []

    if not is_system_admin:
        # HR business scope strictly excludes admin & executive system accounts
        where_clauses.append("e.role IN ('employee', 'manager', 'hr')")
    if role and role != "all":
        if not is_system_admin and role in PRIVILEGED_SYSTEM_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Nhân sự (HR) không có quyền truy cập tài khoản Admin hoặc Executive.",
            )
        where_clauses.append("e.role = ?")
        params.append(role)
    if search:
        like = f"%{search.strip()}%"
        where_clauses.append("(u.username LIKE ? OR e.employee_id LIKE ? OR e.full_name LIKE ?)")
        params.extend([like, like, like])

    rows = conn.execute(
        f"""
        SELECT
            u.user_id,
            u.username,
            u.employee_id,
            e.full_name,
            e.department_id,
            d.name AS department_name,
            e.role,
            u.is_active,
            e.employment_status,
            u.must_change_password,
            u.last_login_at,
            u.created_at
        FROM users u
        JOIN employees e ON e.employee_id = u.employee_id
        JOIN departments d ON d.department_id = e.department_id
        WHERE {' AND '.join(where_clauses)}
        ORDER BY u.user_id
        """,
        params,
    ).fetchall()
    return {
        "total": len(rows),
        "can_manage_all_roles": is_system_admin,
        "assignable_roles": (
            ["employee", "manager", "hr", "executive", "admin"]
            if is_system_admin
            else ["employee", "manager", "hr"]
        ),
        "items": [dict(r) for r in rows],
    }


@router.get("/accounts/unlinked-employees")
def list_unlinked_employees_for_accounts(
    current_user: AuthenticatedUser = Depends(require_permissions("account.manage", "account.manage.business")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
):
    """Minimal identity list of employees without login accounts so Admin never needs HR business /api/employees access."""
    is_system_admin = current_user.has_permission("account.manage")
    role_filter = "" if is_system_admin else "AND e.role IN ('employee', 'manager', 'hr')"
    rows = conn.execute(
        f"""
        SELECT e.employee_id, e.full_name, d.name AS department_name, e.role
        FROM employees e
        JOIN departments d ON d.department_id = e.department_id
        LEFT JOIN users u ON u.employee_id = e.employee_id
        WHERE u.user_id IS NULL
          AND e.employment_status = 'active'
          {role_filter}
        ORDER BY e.employee_id
        """
    ).fetchall()
    return {"total": len(rows), "items": [dict(r) for r in rows]}


@router.post("/accounts", status_code=status.HTTP_201_CREATED)
def create_account(
    payload: AccountCreateRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("account.manage", "account.manage.business")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
):
    is_system_admin = current_user.has_permission("account.manage")
    username = payload.username.strip().lower()
    emp = conn.execute("SELECT employee_id, role FROM employees WHERE employee_id = ?", (payload.employee_id,)).fetchone()
    if not emp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy nhân viên để liên kết tài khoản.")

    target_role = payload.role.value if payload.role else emp["role"]
    if not is_system_admin and (emp["role"] in PRIVILEGED_SYSTEM_ROLES or target_role in PRIVILEGED_SYSTEM_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nhân sự (HR) không có quyền tạo tài khoản với vai trò Admin hoặc Executive.",
        )

    if conn.execute("SELECT 1 FROM users WHERE LOWER(username) = ?", (username,)).fetchone():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tên đăng nhập đã tồn tại.")
    if conn.execute("SELECT 1 FROM users WHERE employee_id = ?", (payload.employee_id,)).fetchone():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Nhân viên này đã có tài khoản đăng nhập.")

    if payload.role and payload.role.value != emp["role"]:
        conn.execute("UPDATE employees SET role = ? WHERE employee_id = ?", (target_role, payload.employee_id))

    user_id = f"USR-{uuid.uuid4().hex[:8].upper()}"
    pwd_hash = hash_password(payload.password)
    conn.execute(
        """
        INSERT INTO users (user_id, username, password_hash, employee_id, is_active, must_change_password)
        VALUES (?, ?, ?, ?, 1, ?)
        """,
        (user_id, username, pwd_hash, payload.employee_id, 1 if payload.must_change_password else 0),
    )
    sync_user_role_mapping(conn, user_id, target_role, assigned_by_user_id=current_user.user_id)
    write_activity_log(
        conn,
        actor_user_id=current_user.user_id,
        action="create_account",
        entity_type="user",
        entity_id=user_id,
        after_obj={"username": username, "employee_id": payload.employee_id, "role": target_role},
    )
    conn.commit()
    return {"status": "ok", "user_id": user_id, "username": username, "employee_id": payload.employee_id, "role": target_role}


@router.patch("/accounts/{user_id}")
def update_account(
    user_id: str,
    payload: AccountUpdateRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("account.manage", "account.manage.business")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
):
    is_system_admin = current_user.has_permission("account.manage")
    existing = conn.execute(
        """
        SELECT u.user_id, u.username, u.employee_id, u.is_active, u.must_change_password, e.role, e.employment_status
        FROM users u
        JOIN employees e ON e.employee_id = u.employee_id
        WHERE u.user_id = ?
        """,
        (user_id,),
    ).fetchone()
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy tài khoản.")

    # HR MUST NOT modify admin/executive accounts or promote anyone to admin/executive
    if not is_system_admin:
        if existing["role"] in PRIVILEGED_SYSTEM_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Nhân sự (HR) không có quyền chỉnh sửa hoặc khóa tài khoản Admin/Executive.",
            )
        if payload.role is not None and payload.role.value in PRIVILEGED_SYSTEM_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Nhân sự (HR) không được phép nâng quyền tài khoản lên Admin hoặc Executive.",
            )

    before_obj = dict(existing)

    # Protect last active Admin account (including self-lock) AND last active HR account
    if existing["is_active"] == 1:
        for protected_role, label in [("admin", "Quản trị viên (Admin)"), ("hr", "HR")]:
            if existing["role"] == protected_role:
                locking = payload.is_active is False
                demoting = payload.role is not None and payload.role.value != protected_role
                if (locking or demoting) and _count_active_accounts_by_role(
                    conn, protected_role, exclude_user_id=user_id
                ) == 0:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Không thể khóa hoặc hạ quyền tài khoản {label} cuối cùng còn hoạt động.",
                    )

    if payload.role is not None:
        conn.execute(
            "UPDATE employees SET role = ? WHERE employee_id = ?",
            (payload.role.value, existing["employee_id"]),
        )
        sync_user_role_mapping(conn, user_id, payload.role.value, assigned_by_user_id=current_user.user_id)
    if payload.is_active is not None:
        conn.execute(
            "UPDATE users SET is_active = ? WHERE user_id = ?",
            (1 if payload.is_active else 0, user_id),
        )
    if payload.reset_password is not None:
        new_hash = hash_password(payload.reset_password)
        must_change = 1 if (payload.must_change_password is None or payload.must_change_password) else 0
        conn.execute(
            "UPDATE users SET password_hash = ?, must_change_password = ? WHERE user_id = ?",
            (new_hash, must_change, user_id),
        )
    elif payload.must_change_password is not None:
        conn.execute(
            "UPDATE users SET must_change_password = ? WHERE user_id = ?",
            (1 if payload.must_change_password else 0, user_id),
        )

    after_row = conn.execute(
        """
        SELECT u.user_id, u.username, u.employee_id, u.is_active, u.must_change_password, e.role
        FROM users u
        JOIN employees e ON e.employee_id = u.employee_id
        WHERE u.user_id = ?
        """,
        (user_id,),
    ).fetchone()

    after_obj = dict(after_row)
    if payload.reset_password is not None:
        after_obj["password_reset"] = True  # Never log plaintext password!

    action_name = "change_role" if (payload.role is not None and payload.role.value != existing["role"]) else "update_account"
    write_activity_log(
        conn,
        actor_user_id=current_user.user_id,
        action=action_name,
        entity_type="user",
        entity_id=user_id,
        before_obj=before_obj,
        after_obj=after_obj,
    )
    conn.commit()
    return {"status": "ok", "account": dict(after_row)}


# =============================================================================
# 4. ACTIVITY AUDIT LOGS (ADMIN FULL; HR BUSINESS AUDIT ONLY)
# =============================================================================

@router.get("/audit/activity")
def list_activity_logs(
    action: Optional[str] = Query(default=None),
    entity_type: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: AuthenticatedUser = Depends(require_permissions("audit.read", "audit.read.business")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
):
    is_full_audit = current_user.has_permission("audit.read")
    where_clauses = ["1 = 1"]
    params: List[Any] = []

    if not is_full_audit:
        placeholders = ", ".join("?" for _ in TECHNICAL_AUDIT_ACTIONS)
        where_clauses.append(f"al.action NOT IN ({placeholders})")
        params.extend(TECHNICAL_AUDIT_ACTIONS)
    if action and action != "all":
        where_clauses.append("al.action = ?")
        params.append(action)
    if entity_type and entity_type != "all":
        where_clauses.append("al.entity_type = ?")
        params.append(entity_type)

    rows = conn.execute(
        f"""
        SELECT al.id, al.actor_user_id, u.username AS actor_username, al.action,
               al.entity_type, al.entity_id, al.before_json, al.after_json, al.created_at
        FROM activity_logs al
        LEFT JOIN users u ON u.user_id = al.actor_user_id
        WHERE {' AND '.join(where_clauses)}
        ORDER BY al.id DESC
        LIMIT ?
        """,
        [*params, limit],
    ).fetchall()
    return {"total": len(rows), "scope": "system" if is_full_audit else "business", "items": [dict(r) for r in rows]}
