from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.common import RoleEnum


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=120)
    password: str = Field(..., min_length=1, max_length=128)


class UserProfileResponse(BaseModel):
    user_id: str
    username: str
    employee_id: str
    full_name: str
    role: RoleEnum
    department_id: str
    department_name: str
    position: str
    manager_id: Optional[str] = None
    manager_name: Optional[str] = None
    start_date: str
    annual_leave_balance: float
    used_annual_leave: float
    remaining_annual_leave: float
    employment_status: str
    email: Optional[str] = None
    phone: Optional[str] = None
    must_change_password: bool = False
    allowed_screens: List[str] = []


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserProfileResponse


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6, max_length=128)


class SelfProfileUpdateRequest(BaseModel):
    """Strictly allow only safe contact fields; reject extra fields like role/department_id."""
    model_config = ConfigDict(extra="forbid")
    phone: Optional[str] = Field(default=None, max_length=30)


class EmployeeCreateRequest(BaseModel):
    employee_id: str = Field(..., min_length=3, max_length=20)
    full_name: str = Field(..., min_length=2, max_length=120)
    department_id: str
    position: str = Field(..., min_length=2, max_length=120)
    manager_id: Optional[str] = None
    start_date: str
    annual_leave_balance: float = Field(default=12.0, ge=0, le=60)
    role: RoleEnum = RoleEnum.employee
    email: Optional[str] = None
    phone: Optional[str] = None


class EmployeeUpdateRequest(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    department_id: Optional[str] = None
    position: Optional[str] = Field(default=None, min_length=2, max_length=120)
    manager_id: Optional[str] = None
    annual_leave_balance: Optional[float] = Field(default=None, ge=0, le=60)
    role: Optional[RoleEnum] = None
    employment_status: Optional[str] = Field(default=None, pattern="^(active|inactive|terminated)$")
    email: Optional[str] = None
    phone: Optional[str] = None


class AccountCreateRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=120)
    employee_id: str
    password: str = Field(..., min_length=6, max_length=128)
    must_change_password: bool = True


class AccountUpdateRequest(BaseModel):
    role: Optional[RoleEnum] = None
    is_active: Optional[bool] = None
    reset_password: Optional[str] = Field(default=None, min_length=6, max_length=128)
    must_change_password: Optional[bool] = None
