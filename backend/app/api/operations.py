from __future__ import annotations

import datetime
import sqlite3
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response

from app.core.security import (
    AuthenticatedUser,
    assert_department_access,
    assert_employee_access,
    build_scope_filter,
    get_current_user,
    get_db_dependency,
    require_roles,
    write_activity_log,
)
from app.schemas.common import RoleEnum
from app.schemas.operations import ImportConfirmRequest, LeaveCreateRequest, LeaveReviewRequest
from app.services.import_service import (
    confirm_staged_import,
    export_batch_errors_csv,
    generate_template_xlsx,
    stage_and_validate_import,
)

router = APIRouter(prefix="/api", tags=["attendance-leave-import"])


# =============================================================================
# 1. ATTENDANCE HISTORY (READ-ONLY, RBAC-SCOPED)
# =============================================================================

@router.get("/attendance")
def list_attendance(
    period: Optional[str] = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    date_from: Optional[str] = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: Optional[str] = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    status_filter: Optional[str] = Query(default="all", alias="status"),
    department_id: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    effective_dept = assert_department_access(current_user, department_id)
    scope_sql, scope_params = build_scope_filter(current_user, "employee_id", "department_id")

    where_clauses = [scope_sql]
    params: List[Any] = [*scope_params]

    if effective_dept and current_user.role == RoleEnum.hr:
        where_clauses.append("department_id = ?")
        params.append(effective_dept)
    if period:
        where_clauses.append("period = ?")
        params.append(period)
    if date_from:
        where_clauses.append("work_date >= ?")
        params.append(date_from)
    if date_to:
        where_clauses.append("work_date <= ?")
        params.append(date_to)

    if status_filter and status_filter != "all":
        if status_filter == "on_time":
            where_clauses.append("status = 'present' AND is_late = 0 AND check_in IS NOT NULL AND check_out IS NOT NULL")
        elif status_filter == "late":
            where_clauses.append("is_late = 1")
        elif status_filter == "missing_punch":
            where_clauses.append("status = 'present' AND (check_in IS NULL OR check_out IS NULL)")
        elif status_filter in ("present", "absent", "on_leave", "holiday", "weekend"):
            where_clauses.append("status = ?")
            params.append(status_filter)

    if search and current_user.role != RoleEnum.employee:
        like = f"%{search.strip()}%"
        where_clauses.append("(employee_id LIKE ? OR full_name LIKE ?)")
        params.extend([like, like])

    where_str = " AND ".join(where_clauses)
    total = int(conn.execute(f"SELECT COUNT(*) FROM v_attendance_daily WHERE {where_str}", params).fetchone()[0])

    offset = (page - 1) * page_size
    rows = conn.execute(
        f"""
        SELECT
            id, employee_id, full_name, department_id, department_name,
            work_date, period, check_in, check_out, work_hours, late_minutes,
            is_late, status, source, is_weekend, is_holiday
        FROM v_attendance_daily
        WHERE {where_str}
        ORDER BY work_date DESC, employee_id ASC
        LIMIT ? OFFSET ?
        """,
        [*params, page_size, offset],
    ).fetchall()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
        "items": [dict(r) for r in rows],
    }


@router.get("/attendance/{record_id}")
def get_attendance_detail(
    record_id: int,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db_dependency),
):
    row = conn.execute("SELECT * FROM v_attendance_daily WHERE id = ?", (record_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy bản ghi chấm công.")
    assert_employee_access(conn, current_user, row["employee_id"])
    return dict(row)


# =============================================================================
# 2. LEAVE MANAGEMENT (CREATE, CANCEL, APPROVE/REJECT + AUDIT)
# =============================================================================

def _get_annual_leave_balance_info(conn: sqlite3.Connection, employee_id: str) -> Dict[str, float]:
    emp = conn.execute("SELECT annual_leave_balance FROM employees WHERE employee_id = ?", (employee_id,)).fetchone()
    quota = float(emp["annual_leave_balance"]) if emp else 12.0
    used = conn.execute(
        """
        SELECT COALESCE(SUM(leave_days), 0)
        FROM v_leave_requests
        WHERE employee_id = ? AND leave_type = 'annual' AND status = 'approved'
        """,
        (employee_id,),
    ).fetchone()[0]
    used_f = float(used or 0.0)
    return {
        "annual_leave_balance": quota,
        "used_annual_leave": used_f,
        "remaining_annual_leave": max(0.0, round(quota - used_f, 1)),
    }


@router.get("/leaves")
def list_leaves(
    status_filter: Optional[str] = Query(default="all", alias="status"),
    leave_type: Optional[str] = Query(default="all"),
    period: Optional[str] = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    department_id: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    effective_dept = assert_department_access(current_user, department_id)
    scope_sql, scope_params = build_scope_filter(current_user, "v.employee_id", "v.department_id")

    base_clauses = [scope_sql]
    base_params: List[Any] = [*scope_params]
    if effective_dept and current_user.role == RoleEnum.hr:
        base_clauses.append("v.department_id = ?")
        base_params.append(effective_dept)
    base_where = " AND ".join(base_clauses)

    # Summary KPIs in scope (distinguish period-scoped KPIs vs all-time active pending queue)
    kpi_clauses = [*base_clauses]
    kpi_params: List[Any] = [*base_params]
    if period:
        kpi_clauses.append("v.period = ?")
        kpi_params.append(period)
    kpi_where = " AND ".join(kpi_clauses)

    kpi_row = conn.execute(
        f"""
        SELECT
            SUM(CASE WHEN v.status = 'pending' THEN 1 ELSE 0 END) AS pending_count,
            SUM(CASE WHEN v.status = 'approved' THEN 1 ELSE 0 END) AS approved_count,
            SUM(CASE WHEN v.status = 'rejected' THEN 1 ELSE 0 END) AS rejected_count
        FROM v_leave_requests v
        WHERE {kpi_where}
        """,
        kpi_params,
    ).fetchone()

    pending_all = int(
        conn.execute(
            f"SELECT COUNT(*) FROM v_leave_requests v WHERE {base_where} AND v.status = 'pending'",
            base_params,
        ).fetchone()[0]
    )

    where_clauses = [*base_clauses]
    params = [*base_params]
    if status_filter and status_filter != "all":
        where_clauses.append("v.status = ?")
        params.append(status_filter)
    if leave_type and leave_type != "all":
        where_clauses.append("v.leave_type = ?")
        params.append(leave_type)
    if period:
        where_clauses.append("v.period = ?")
        params.append(period)
    if search and current_user.role != RoleEnum.employee:
        like = f"%{search.strip()}%"
        where_clauses.append("(v.employee_id LIKE ? OR v.full_name LIKE ? OR v.reason LIKE ?)")
        params.extend([like, like, like])

    rows = conn.execute(
        f"""
        SELECT v.*, e.role AS requester_role
        FROM v_leave_requests v
        JOIN employees e ON e.employee_id = v.employee_id
        WHERE {' AND '.join(where_clauses)}
        ORDER BY v.created_at DESC, v.request_id DESC
        """,
        params,
    ).fetchall()

    items = []
    for r in rows:
        item = dict(r)
        # BUG-07: Sync UI can_review strictly with POST /api/leaves/{id}/review rules
        can_review = False
        if item["status"] == "pending":
            if current_user.role == RoleEnum.hr and item["employee_id"] != current_user.employee_id:
                can_review = True
            elif (
                current_user.role == RoleEnum.manager
                and item["department_id"] == current_user.department_id
                and item["employee_id"] != current_user.employee_id
                and item["requester_role"] == "employee"
            ):
                can_review = True
        item["can_review"] = can_review
        item["can_cancel"] = item["status"] == "pending" and item["employee_id"] == current_user.employee_id
        items.append(item)

    return {
        "total": len(items),
        "period": period or "all",
        "kpis": {
            "pending": int(kpi_row["pending_count"] or 0),
            "pending_all": pending_all,
            "approved": int(kpi_row["approved_count"] or 0),
            "rejected": int(kpi_row["rejected_count"] or 0),
        },
        "my_balance": _get_annual_leave_balance_info(conn, current_user.employee_id),
        "items": items,
    }


@router.get("/leaves/{request_id}")
def get_leave_detail(
    request_id: int,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db_dependency),
):
    row = conn.execute("SELECT * FROM v_leave_requests WHERE request_id = ?", (request_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy đơn nghỉ phép.")
    assert_employee_access(conn, current_user, row["employee_id"])

    logs = conn.execute(
        """
        SELECT l.id, l.action, l.note, l.created_at, u.username AS actor_username, e.full_name AS actor_name
        FROM leave_approval_logs l
        LEFT JOIN users u ON u.user_id = l.actor_user_id
        LEFT JOIN employees e ON e.employee_id = u.employee_id
        WHERE l.request_id = ?
        ORDER BY l.id ASC
        """,
        (request_id,),
    ).fetchall()
    return {"request": dict(row), "timeline": [dict(l) for l in logs]}


@router.post("/leaves", status_code=status.HTTP_201_CREATED)
def create_leave_request(
    payload: LeaveCreateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db_dependency),
):
    try:
        f_dt = datetime.date.fromisoformat(payload.from_date)
        t_dt = datetime.date.fromisoformat(payload.to_date)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ngày nghỉ không hợp lệ.")

    if t_dt < f_dt:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ngày kết thúc phải lớn hơn hoặc bằng ngày bắt đầu.")

    # Calendar days inclusive (matching PDF specification)
    requested_days = (t_dt - f_dt).days + 1

    # Overlap check against pending/approved leaves
    overlap = conn.execute(
        """
        SELECT request_id FROM leave_requests
        WHERE employee_id = ? AND status IN ('pending', 'approved')
          AND NOT (to_date < ? OR from_date > ?)
        """,
        (current_user.employee_id, payload.from_date, payload.to_date),
    ).fetchone()
    if overlap:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Khoảng thời gian nghỉ bị trùng với một đơn đang chờ duyệt hoặc đã được duyệt.",
        )

    # Validate annual leave balance (do NOT deduct yet while pending)
    if payload.leave_type == "annual":
        bal = _get_annual_leave_balance_info(conn, current_user.employee_id)
        if requested_days > bal["remaining_annual_leave"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Số ngày phép năm còn lại ({bal['remaining_annual_leave']} ngày) không đủ cho đơn {requested_days} ngày.",
            )

    cur = conn.execute(
        """
        INSERT INTO leave_requests (employee_id, leave_type, from_date, to_date, reason, status)
        VALUES (?, ?, ?, ?, ?, 'pending')
        """,
        (current_user.employee_id, payload.leave_type, payload.from_date, payload.to_date, payload.reason.strip()),
    )
    req_id = cur.lastrowid

    conn.execute(
        """
        INSERT INTO leave_approval_logs (request_id, actor_user_id, action, note)
        VALUES (?, ?, 'submit', ?)
        """,
        (req_id, current_user.user_id, payload.reason.strip()),
    )
    write_activity_log(
        conn,
        actor_user_id=current_user.user_id,
        action="create_leave_request",
        entity_type="leave_request",
        entity_id=str(req_id),
        after_obj={"employee_id": current_user.employee_id, "from_date": payload.from_date, "to_date": payload.to_date, "leave_days": requested_days},
    )
    conn.commit()
    created = conn.execute("SELECT * FROM v_leave_requests WHERE request_id = ?", (req_id,)).fetchone()
    return {"status": "ok", "request": dict(created)}


@router.post("/leaves/{request_id}/cancel")
def cancel_leave_request(
    request_id: int,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db_dependency),
):
    row = conn.execute("SELECT * FROM leave_requests WHERE request_id = ?", (request_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy đơn nghỉ phép.")
    if row["employee_id"] != current_user.employee_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bạn chỉ có thể hủy đơn nghỉ phép của chính mình.")
    if row["status"] != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Chỉ có thể hủy đơn khi đang ở trạng thái chờ duyệt (pending).")

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE leave_requests SET status = 'cancelled', cancelled_at = ? WHERE request_id = ?",
        (now_str, request_id),
    )
    conn.execute(
        "INSERT INTO leave_approval_logs (request_id, actor_user_id, action, note) VALUES (?, ?, 'cancel', 'Nhân viên tự hủy đơn')",
        (request_id, current_user.user_id),
    )
    write_activity_log(
        conn,
        actor_user_id=current_user.user_id,
        action="cancel_leave_request",
        entity_type="leave_request",
        entity_id=str(request_id),
        before_obj={"status": "pending"},
        after_obj={"status": "cancelled"},
    )
    conn.commit()
    return {"status": "ok", "request_id": request_id, "new_status": "cancelled"}


@router.post("/leaves/{request_id}/review")
def review_leave_request(
    request_id: int,
    payload: LeaveReviewRequest,
    current_user: AuthenticatedUser = Depends(require_roles(RoleEnum.manager, RoleEnum.hr)),
    conn: sqlite3.Connection = Depends(get_db_dependency),
):
    row = conn.execute(
        """
        SELECT lr.*, e.department_id, e.role AS requester_role
        FROM leave_requests lr
        JOIN employees e ON e.employee_id = lr.employee_id
        WHERE lr.request_id = ?
        """,
        (request_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy đơn nghỉ phép.")

    # Never allow self-approval
    if row["employee_id"] == current_user.employee_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Không được phép tự duyệt đơn nghỉ phép của chính mình.",
        )

    # Manager can only review employees in their own department (and not other managers/HR)
    if current_user.role == RoleEnum.manager:
        if row["department_id"] != current_user.department_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Trưởng phòng chỉ được duyệt đơn nghỉ phép của nhân viên thuộc phòng ban mình.",
            )
        if row["requester_role"] != "employee":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Đơn nghỉ phép của cấp quản lý cần được bộ phận Nhân sự (HR) phê duyệt.",
            )

    if row["status"] != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Đơn nghỉ phép đang ở trạng thái '{row['status']}', không thể phê duyệt lại.",
        )

    note = (payload.decision_note or "").strip()
    if payload.decision == "rejected" and not note:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bắt buộc phải nhập lý do khi từ chối đơn nghỉ phép.",
        )

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        UPDATE leave_requests
        SET status = ?, reviewed_by = ?, reviewed_at = ?, decision_note = ?
        WHERE request_id = ?
        """,
        (payload.decision, current_user.employee_id, now_str, note or "Đã phê duyệt", request_id),
    )

    # Only when approved: sync weekdays (non-holidays) to attendance table as on_leave if not present
    if payload.decision == "approved":
        holiday_set = {r[0] for r in conn.execute("SELECT holiday_date FROM holidays").fetchall()}
        cur_d = datetime.date.fromisoformat(row["from_date"])
        end_d = datetime.date.fromisoformat(row["to_date"])
        while cur_d <= end_d:
            d_str = cur_d.isoformat()
            if cur_d.weekday() < 5 and d_str not in holiday_set:
                existing_att = conn.execute(
                    "SELECT id, status FROM attendance WHERE employee_id = ? AND work_date = ?",
                    (row["employee_id"], d_str),
                ).fetchone()
                if not existing_att:
                    conn.execute(
                        """
                        INSERT INTO attendance (employee_id, work_date, check_in, check_out, status, source)
                        VALUES (?, ?, NULL, NULL, 'on_leave', 'leave_system')
                        """,
                        (row["employee_id"], d_str),
                    )
                elif existing_att["status"] == "absent":
                    conn.execute(
                        "UPDATE attendance SET status = 'on_leave', source = 'leave_system' WHERE id = ?",
                        (existing_att["id"],),
                    )
            cur_d += datetime.timedelta(days=1)

    log_action = "approve" if payload.decision == "approved" else "reject"
    if current_user.role == RoleEnum.hr and row["department_id"] != current_user.department_id:
        log_action = "override" if payload.decision == "approved" else "reject"

    conn.execute(
        """
        INSERT INTO leave_approval_logs (request_id, actor_user_id, action, note)
        VALUES (?, ?, ?, ?)
        """,
        (request_id, current_user.user_id, log_action, note or "Đã phê duyệt"),
    )
    write_activity_log(
        conn,
        actor_user_id=current_user.user_id,
        action=f"leave_{payload.decision}",
        entity_type="leave_request",
        entity_id=str(request_id),
        before_obj={"status": "pending"},
        after_obj={"status": payload.decision, "decision_note": note},
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM v_leave_requests WHERE request_id = ?", (request_id,)).fetchone()
    return {"status": "ok", "request": dict(updated)}


# =============================================================================
# 3. DATA IMPORT EXCEL / CSV (HR ONLY: TEMPLATE -> PREVIEW -> CONFIRM -> LOGS)
# =============================================================================

@router.get("/imports/template/{data_type}")
def download_import_template(
    data_type: str,
    current_user: AuthenticatedUser = Depends(require_roles(RoleEnum.hr)),
):
    try:
        content = generate_template_xlsx(data_type)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="template_{data_type}.xlsx"'},
    )


@router.post("/imports/preview")
async def preview_import(
    data_type: str = Form(...),
    file: UploadFile = File(...),
    current_user: AuthenticatedUser = Depends(require_roles(RoleEnum.hr)),
    conn: sqlite3.Connection = Depends(get_db_dependency),
):
    raw_bytes = await file.read()
    try:
        result = stage_and_validate_import(
            conn=conn,
            actor_user_id=current_user.user_id,
            file_name=file.filename or "upload.csv",
            data_type=data_type,
            raw_bytes=raw_bytes,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/imports/errors/{batch_id}")
def download_import_errors(
    batch_id: str,
    current_user: AuthenticatedUser = Depends(require_roles(RoleEnum.hr)),
):
    try:
        csv_text = export_batch_errors_csv(batch_id, actor_user_id=current_user.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return Response(
        content=csv_text.encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="errors_{batch_id}.csv"'},
    )


@router.post("/imports/confirm/{batch_id}")
def confirm_import(
    batch_id: str,
    payload: ImportConfirmRequest,
    current_user: AuthenticatedUser = Depends(require_roles(RoleEnum.hr)),
    conn: sqlite3.Connection = Depends(get_db_dependency),
):
    try:
        return confirm_staged_import(
            conn=conn,
            batch_id=batch_id,
            actor_user_id=current_user.user_id,
            duplicate_policy=payload.duplicate_policy,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/imports/logs")
def list_import_logs(
    current_user: AuthenticatedUser = Depends(require_roles(RoleEnum.hr)),
    conn: sqlite3.Connection = Depends(get_db_dependency),
):
    rows = conn.execute(
        """
        SELECT il.*, u.username AS uploaded_by_username
        FROM import_logs il
        LEFT JOIN users u ON u.user_id = il.uploaded_by
        ORDER BY il.id DESC
        LIMIT 50
        """
    ).fetchall()
    return {"total": len(rows), "items": [dict(r) for r in rows]}
