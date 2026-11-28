from __future__ import annotations

import datetime
import json
import sqlite3
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.security import (
    AuthenticatedUser,
    assert_department_access,
    get_db_dependency,
    require_permissions,
    write_activity_log,
)
from app.schemas.common import RoleEnum
from app.services.anomaly_service import run_anomaly_scan

router = APIRouter(prefix="/api/anomalies", tags=["anomalies"])


class AnomalyReviewRequest(BaseModel):
    review_status: str = Field(..., pattern="^(confirmed|dismissed|open)$")
    review_note: Optional[str] = Field(default=None, max_length=500)


def _anomaly_scope_where(user: AuthenticatedUser) -> tuple[str, List[Any]]:
    if user.role in (RoleEnum.hr, RoleEnum.executive):
        return "1 = 1", []
    if user.role == RoleEnum.manager:
        return "department_id = ?", [user.department_id]
    if user.role == RoleEnum.employee:
        # Employee only sees their own personal anomalies (never exposes colleagues inside department R5!)
        return "scope_type = 'employee' AND employee_id = ?", [user.employee_id]
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Quản trị hệ thống (Admin) không mặc định truy cập dữ liệu cảnh báo nghiệp vụ R1-R8.",
    )


def _serialize_anomaly(row: sqlite3.Row, user: AuthenticatedUser) -> Dict[str, Any]:
    d = dict(row)
    try:
        raw_ev = d.get("evidence")
        if isinstance(raw_ev, dict):
            d["evidence_data"] = raw_ev
        elif isinstance(raw_ev, str):
            d["evidence_data"] = json.loads(raw_ev)
        else:
            d["evidence_data"] = {}
    except Exception:
        d["evidence_data"] = {}
    d["can_review"] = user.has_permission("anomaly.review")
    return d


@router.post("/scan")
def trigger_anomaly_scan(
    period: Optional[str] = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    current_user: AuthenticatedUser = Depends(require_permissions("anomaly.review")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    if current_user.role not in (RoleEnum.manager, RoleEnum.hr):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ Trưởng phòng (trong phòng mình) hoặc Nhân sự (HR) mới được chạy quét cảnh báo nghiệp vụ R1-R8.",
        )
    scope_dept = current_user.department_id if current_user.role == RoleEnum.manager else None
    result = run_anomaly_scan(conn, period=period, department_id=scope_dept)
    write_activity_log(
        conn,
        actor_user_id=current_user.user_id,
        action="scan_anomalies",
        entity_type="anomaly_engine",
        entity_id=f"{period or 'all'}:{scope_dept or 'company'}",
        after_obj=result,
    )
    conn.commit()
    return result


@router.get("")
def list_anomalies(
    period: Optional[str] = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    rule_code: Optional[str] = Query(default="all"),
    severity: Optional[str] = Query(default="all"),
    review_status: Optional[str] = Query(default="all"),
    department_id: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    current_user: AuthenticatedUser = Depends(
        require_permissions("anomaly.read.self", "anomaly.read.department", "anomaly.read.all")
    ),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    effective_dept = assert_department_access(current_user, department_id)
    scope_sql, scope_params = _anomaly_scope_where(current_user)

    base_clauses = [scope_sql]
    base_params: List[Any] = [*scope_params]
    if effective_dept and current_user.role in (RoleEnum.hr, RoleEnum.executive):
        base_clauses.append("department_id = ?")
        base_params.append(effective_dept)
    if period:
        base_clauses.append("period = ?")
        base_params.append(period)
    base_where = " AND ".join(base_clauses)

    summary_row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN review_status = 'open' THEN 1 ELSE 0 END) AS open_count,
            SUM(CASE WHEN review_status = 'confirmed' THEN 1 ELSE 0 END) AS confirmed_count,
            SUM(CASE WHEN review_status = 'dismissed' THEN 1 ELSE 0 END) AS dismissed_count,
            SUM(CASE WHEN severity = 'high' THEN 1 ELSE 0 END) AS high_count,
            SUM(CASE WHEN severity = 'medium' THEN 1 ELSE 0 END) AS medium_count,
            SUM(CASE WHEN severity = 'low' THEN 1 ELSE 0 END) AS low_count
        FROM v_anomalies
        WHERE {base_where}
        """,
        base_params,
    ).fetchone()

    where_clauses = [*base_clauses]
    params = [*base_params]
    if rule_code and rule_code != "all":
        where_clauses.append("rule_code = ?")
        params.append(rule_code.upper())
    if severity and severity != "all":
        where_clauses.append("severity = ?")
        params.append(severity.lower())
    if review_status and review_status != "all":
        where_clauses.append("review_status = ?")
        params.append(review_status.lower())
    if search and current_user.role != RoleEnum.employee:
        like = f"%{search.strip()}%"
        where_clauses.append("(COALESCE(employee_id, '') LIKE ? OR COALESCE(full_name, '') LIKE ? OR COALESCE(department_name, '') LIKE ?)")
        params.extend([like, like, like])

    rows = conn.execute(
        f"""
        SELECT *
        FROM v_anomalies
        WHERE {' AND '.join(where_clauses)}
        ORDER BY
            CASE review_status WHEN 'open' THEN 1 WHEN 'confirmed' THEN 2 ELSE 3 END,
            CASE severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
            period DESC,
            anomaly_id DESC
        """,
        params,
    ).fetchall()

    return {
        "total": len(rows),
        "can_review": current_user.has_permission("anomaly.review"),
        "summary": {
            "total": int(summary_row["total"] or 0),
            "open": int(summary_row["open_count"] or 0),
            "confirmed": int(summary_row["confirmed_count"] or 0),
            "dismissed": int(summary_row["dismissed_count"] or 0),
            "high": int(summary_row["high_count"] or 0),
            "medium": int(summary_row["medium_count"] or 0),
            "low": int(summary_row["low_count"] or 0),
        },
        "items": [_serialize_anomaly(r, current_user) for r in rows],
    }


@router.get("/{anomaly_id}")
def get_anomaly_detail(
    anomaly_id: int,
    current_user: AuthenticatedUser = Depends(
        require_permissions("anomaly.read.self", "anomaly.read.department", "anomaly.read.all")
    ),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM v_anomalies WHERE anomaly_id = ?", (anomaly_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy cảnh báo bất thường.")

    if current_user.role == RoleEnum.employee:
        if row["scope_type"] != "employee" or row["employee_id"] != current_user.employee_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bạn không có quyền xem cảnh báo này.")
    elif current_user.role == RoleEnum.manager:
        if row["department_id"] != current_user.department_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Trưởng phòng chỉ được xem cảnh báo của phòng mình.")
    elif current_user.role in (RoleEnum.hr, RoleEnum.executive):
        if not current_user.has_permission("anomaly.read.all") and row["department_id"] != current_user.department_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tài khoản không có quyền xem cảnh báo ngoài phòng ban.")
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Quản trị hệ thống (Admin) không mặc định truy cập dữ liệu cảnh báo nghiệp vụ R1-R8.",
        )

    return _serialize_anomaly(row, current_user)


@router.post("/{anomaly_id}/review")
def review_anomaly(
    anomaly_id: int,
    payload: AnomalyReviewRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("anomaly.review")),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    if current_user.role not in (RoleEnum.manager, RoleEnum.hr):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ Trưởng phòng (phòng mình) hoặc Nhân sự (HR) mới được xử lý cảnh báo nghiệp vụ R1-R8.",
        )
    row = conn.execute("SELECT * FROM v_anomalies WHERE anomaly_id = ?", (anomaly_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy cảnh báo bất thường.")

    if current_user.role == RoleEnum.manager and row["department_id"] != current_user.department_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Trưởng phòng chỉ được xử lý cảnh báo thuộc phòng ban mình quản lý.",
        )

    before_obj = {"review_status": row["review_status"], "review_note": row["review_note"]}
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    note = (payload.review_note or "").strip() or None

    conn.execute(
        """
        UPDATE anomalies
        SET review_status = ?, reviewed_by = ?, reviewed_at = ?, review_note = ?
        WHERE anomaly_id = ?
        """,
        (payload.review_status, current_user.employee_id, now_str, note, anomaly_id),
    )
    write_activity_log(
        conn,
        actor_user_id=current_user.user_id,
        action="review_anomaly",
        entity_type="anomaly",
        entity_id=str(anomaly_id),
        before_obj=before_obj,
        after_obj={"review_status": payload.review_status, "review_note": note, "reviewed_by": current_user.employee_id},
    )
    conn.commit()
    refreshed = conn.execute("SELECT * FROM v_anomalies WHERE anomaly_id = ?", (anomaly_id,)).fetchone()
    return {"status": "ok", "anomaly": _serialize_anomaly(refreshed, current_user)}
