from typing import List
from fastapi import APIRouter
from app.core.config import settings
from app.schemas.common import HealthResponse, NavigationScreen, RoleEnum, SitemapResponse

router = APIRouter(prefix="/api")


def build_screens(allow_manager_employee_read: bool = True) -> List[NavigationScreen]:
    employee_mgmt_roles = [RoleEnum.hr, RoleEnum.manager] if allow_manager_employee_read else [RoleEnum.hr]
    return [
        NavigationScreen(id="face-attendance", code="11", title="Máy chấm công khuôn mặt",
                         path="/face-attendance", group="Quản trị nhân sự", allowed_roles=[RoleEnum.hr]),
        NavigationScreen(
            id="dashboard",
            code="01",
            title="Tổng quan",
            path="/dashboard",
            group="Không gian làm việc",
            allowed_roles=[RoleEnum.employee, RoleEnum.manager, RoleEnum.hr],
        ),
        NavigationScreen(
            id="attendance",
            code="02",
            title="Chấm công",
            path="/attendance",
            group="Không gian làm việc",
            allowed_roles=[RoleEnum.employee, RoleEnum.manager, RoleEnum.hr],
        ),
        NavigationScreen(
            id="leaves",
            code="03",
            title="Đơn nghỉ phép",
            path="/leaves",
            group="Không gian làm việc",
            allowed_roles=[RoleEnum.employee, RoleEnum.manager, RoleEnum.hr],
        ),
        NavigationScreen(
            id="anomalies",
            code="04",
            title="Cảnh báo bất thường",
            path="/anomalies",
            group="Không gian làm việc",
            allowed_roles=[RoleEnum.employee, RoleEnum.manager, RoleEnum.hr],
        ),
        NavigationScreen(
            id="assistant",
            code="05",
            title="Hỏi đáp AI",
            path="/assistant",
            group="Không gian làm việc",
            allowed_roles=[RoleEnum.employee, RoleEnum.manager, RoleEnum.hr],
        ),
        NavigationScreen(
            id="reports",
            code="06",
            title="Báo cáo",
            path="/reports",
            group="Không gian làm việc",
            allowed_roles=[RoleEnum.manager, RoleEnum.hr],
        ),
        NavigationScreen(
            id="profile",
            code="07",
            title="Hồ sơ cá nhân",
            path="/profile",
            group="Cá nhân",
            allowed_roles=[RoleEnum.employee, RoleEnum.manager, RoleEnum.hr],
        ),
        NavigationScreen(
            id="import",
            code="08",
            title="Nhập dữ liệu",
            path="/admin/import",
            group="Quản trị nhân sự",
            allowed_roles=[RoleEnum.hr],
        ),
        NavigationScreen(
            id="employees",
            code="09",
            title="Quản lý nhân viên",
            path="/admin/employees",
            group="Quản trị nhân sự",
            allowed_roles=employee_mgmt_roles,
        ),
        NavigationScreen(
            id="accounts",
            code="10",
            title="Quản lý tài khoản",
            path="/admin/accounts",
            group="Quản trị nhân sự",
            allowed_roles=[RoleEnum.hr],
        ),
    ]


@router.get("/health", response_model=HealthResponse, tags=["system"])
def get_health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.version,
        environment=settings.app_env,
    )


@router.get("/meta/sitemap", response_model=SitemapResponse, tags=["system"])
def get_sitemap() -> SitemapResponse:
    screens = build_screens(settings.allow_manager_employee_read)
    return SitemapResponse(
        total_screens=len(screens),
        roles=[RoleEnum.employee, RoleEnum.manager, RoleEnum.hr],
        screens=screens,
    )
