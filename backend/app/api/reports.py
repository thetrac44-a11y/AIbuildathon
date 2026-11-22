from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.core.security import AuthenticatedUser, get_db_dependency, require_roles, write_activity_log
from app.schemas.common import RoleEnum
from app.services.report_service import build_report, export_report_excel, export_report_pdf

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/preview")
def preview_report(
    period: str = Query(default="2026-10", pattern=r"^\d{4}-\d{2}$"),
    department_id: Optional[str] = Query(default=None),
    current_user: AuthenticatedUser = Depends(require_roles(RoleEnum.manager, RoleEnum.hr)),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> Dict[str, Any]:
    report = build_report(conn, period=period, user=current_user, department_id=department_id)
    write_activity_log(
        conn,
        actor_user_id=current_user.user_id,
        action="preview_report",
        entity_type="report",
        entity_id=f"{period}:{report['scope_label']}",
        after_obj={"period": period, "scope": report["scope_label"], "verified": report["narrative"]["verified"]},
    )
    conn.commit()
    return report


@router.get("/export/excel")
def download_report_excel(
    period: str = Query(default="2026-10", pattern=r"^\d{4}-\d{2}$"),
    department_id: Optional[str] = Query(default=None),
    current_user: AuthenticatedUser = Depends(require_roles(RoleEnum.manager, RoleEnum.hr)),
    conn: sqlite3.Connection = Depends(get_db_dependency),
):
    report = build_report(conn, period=period, user=current_user, department_id=department_id)
    xlsx_bytes = export_report_excel(report)
    filename = f"bao_cao_cham_cong_{period}.xlsx"
    write_activity_log(
        conn,
        actor_user_id=current_user.user_id,
        action="export_report_excel",
        entity_type="report",
        entity_id=filename,
        after_obj={"period": period, "scope": report["scope_label"], "format": "xlsx"},
    )
    conn.commit()
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/pdf")
def download_report_pdf(
    period: str = Query(default="2026-10", pattern=r"^\d{4}-\d{2}$"),
    department_id: Optional[str] = Query(default=None),
    current_user: AuthenticatedUser = Depends(require_roles(RoleEnum.manager, RoleEnum.hr)),
    conn: sqlite3.Connection = Depends(get_db_dependency),
):
    report = build_report(conn, period=period, user=current_user, department_id=department_id)
    pdf_bytes = export_report_pdf(report)
    filename = f"bao_cao_cham_cong_{period}.pdf"
    write_activity_log(
        conn,
        actor_user_id=current_user.user_id,
        action="export_report_pdf",
        entity_type="report",
        entity_id=filename,
        after_obj={"period": period, "scope": report["scope_label"], "format": "pdf"},
    )
    conn.commit()
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
