from typing import List
from fastapi import APIRouter
from app.core.config import settings
from app.db.connection import is_postgres_url
from app.schemas.common import HealthResponse, NavigationScreen, RoleEnum, SitemapResponse

router = APIRouter(prefix="/api")


def build_screens(allow_manager_employee_read: bool = True) -> List[NavigationScreen]:
    employee_mgmt_roles = (
        [RoleEnum.hr, RoleEnum.manager, RoleEnum.executive]
        if allow_manager_employee_read
        else [RoleEnum.hr, RoleEnum.executive]
    )
    return [
        NavigationScreen(
            id="dashboard",
            code="01",
            title="Tổng quan",
            path="/dashboard",
            group="Không gian làm việc",
            any_permissions=["dashboard.self", "dashboard.department", "dashboard.all", "dashboard.executive"],
            allowed_roles=[RoleEnum.employee, RoleEnum.manager, RoleEnum.hr, RoleEnum.executive],
        ),
        NavigationScreen(
            id="attendance",
            code="02",
            title="Chấm công",
            path="/attendance",
            group="Không gian làm việc",
            any_permissions=["attendance.read.self", "attendance.read.department", "attendance.read.all"],
            allowed_roles=[RoleEnum.employee, RoleEnum.manager, RoleEnum.hr, RoleEnum.executive],
        ),
        NavigationScreen(
            id="leaves",
            code="03",
            title="Đơn nghỉ phép",
            path="/leaves",
            group="Không gian làm việc",
            any_permissions=["leave.read.self", "leave.read.department", "leave.read.all"],
            allowed_roles=[RoleEnum.employee, RoleEnum.manager, RoleEnum.hr, RoleEnum.executive],
        ),
        NavigationScreen(
            id="anomalies",
            code="04",
            title="Cảnh báo bất thường",
            path="/anomalies",
            group="Không gian làm việc",
            any_permissions=["anomaly.read.self", "anomaly.read.department", "anomaly.read.all"],
            allowed_roles=[RoleEnum.employee, RoleEnum.manager, RoleEnum.hr, RoleEnum.executive],
        ),
        NavigationScreen(
            id="assistant",
            code="05",
            title="Hỏi đáp AI",
            path="/assistant",
            group="Không gian làm việc",
            any_permissions=["ai.ask.self", "ai.ask.department", "ai.ask.all", "ai.strategy"],
            allowed_roles=[RoleEnum.employee, RoleEnum.manager, RoleEnum.hr, RoleEnum.executive],
        ),
        NavigationScreen(
            id="reports",
            code="06",
            title="Báo cáo",
            path="/reports",
            group="Không gian làm việc",
            any_permissions=["report.read.department", "report.read.all"],
            allowed_roles=[RoleEnum.manager, RoleEnum.hr, RoleEnum.executive],
        ),
        NavigationScreen(
            id="profile",
            code="07",
            title="Hồ sơ cá nhân",
            path="/profile",
            group="Cá nhân",
            permission="profile.read.self",
            allowed_roles=[RoleEnum.employee, RoleEnum.manager, RoleEnum.hr, RoleEnum.executive, RoleEnum.admin],
        ),
        NavigationScreen(
            id="import",
            code="08",
            title="Nhập dữ liệu",
            path="/admin/import",
            group="Quản trị nhân sự",
            permission="import.manage",
            allowed_roles=[RoleEnum.hr],
        ),
        NavigationScreen(
            id="employees",
            code="09",
            title="Quản lý nhân viên",
            path="/admin/employees",
            group="Quản trị nhân sự",
            any_permissions=["employee.read.department", "employee.read.all", "employee.manage"],
            allowed_roles=employee_mgmt_roles,
        ),
        NavigationScreen(
            id="accounts",
            code="10",
            title="Quản lý tài khoản",
            path="/admin/accounts",
            group="Quản trị",
            any_permissions=["account.manage", "account.manage.business"],
            allowed_roles=[RoleEnum.admin, RoleEnum.hr],
        ),
        NavigationScreen(
            id="system_dashboard",
            code="11",
            title="System Dashboard",
            path="/admin/system",
            group="Quản trị hệ thống",
            permission="system.dashboard",
            allowed_roles=[RoleEnum.admin],
        ),
        NavigationScreen(
            id="rbac",
            code="12",
            title="Phân quyền",
            path="/admin/rbac",
            group="Quản trị",
            permission="role.manage",
            allowed_roles=[RoleEnum.admin],
        ),
        NavigationScreen(
            id="audit",
            code="13",
            title="Nhật ký kiểm toán",
            path="/admin/audit",
            group="Quản trị",
            any_permissions=["audit.read", "audit.read.business"],
            allowed_roles=[RoleEnum.admin, RoleEnum.hr],
        ),
        NavigationScreen(
            id="rag",
            code="14",
            title="Kho tài liệu RAG",
            path="/admin/rag",
            group="AI",
            permission="rag.manage",
            allowed_roles=[RoleEnum.admin, RoleEnum.hr],
        ),
        NavigationScreen(
            id="system_config",
            code="15",
            title="Cấu hình hệ thống",
            path="/admin/config",
            group="Quản trị",
            permission="system.manage",
            allowed_roles=[RoleEnum.admin],
        ),
        NavigationScreen(
            id="kiosk",
            code="16",
            title="Face Kiosk",
            path="/admin/kiosk",
            group="Face Kiosk",
            permission="kiosk.manage",
            allowed_roles=[RoleEnum.admin],
        ),
    ]


@router.get("/health", response_model=HealthResponse, tags=["system"])
def get_health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.version,
        environment=settings.app_env,
        database="postgresql (supabase)" if is_postgres_url() else "sqlite",
    )


@router.get("/meta/sitemap", response_model=SitemapResponse, tags=["system"])
def get_sitemap() -> SitemapResponse:
    screens = build_screens(settings.allow_manager_employee_read)
    return SitemapResponse(
        total_screens=len(screens),
        roles=[RoleEnum.employee, RoleEnum.manager, RoleEnum.hr, RoleEnum.executive, RoleEnum.admin],
        screens=screens,
    )
