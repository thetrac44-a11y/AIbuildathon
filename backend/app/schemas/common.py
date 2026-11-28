from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class RoleEnum(str, Enum):
    employee = "employee"
    manager = "manager"
    hr = "hr"
    executive = "executive"
    admin = "admin"


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str
    database: str = "sqlite"


class NavigationScreen(BaseModel):
    id: str
    code: str
    title: str
    path: str
    group: str
    permission: Optional[str] = None
    any_permissions: List[str] = Field(default_factory=list)
    allowed_roles: List[RoleEnum]


class SitemapResponse(BaseModel):
    total_screens: int
    roles: List[RoleEnum]
    screens: List[NavigationScreen]
