from enum import Enum
from typing import List
from pydantic import BaseModel


class RoleEnum(str, Enum):
    employee = "employee"
    manager = "manager"
    hr = "hr"


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
    allowed_roles: List[RoleEnum]


class SitemapResponse(BaseModel):
    total_screens: int
    roles: List[RoleEnum]
    screens: List[NavigationScreen]
