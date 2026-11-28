from typing import Dict, Literal, Optional
from pydantic import BaseModel, Field


class LeaveCreateRequest(BaseModel):
    leave_type: str = Field(..., pattern="^(annual|sick|personal|unpaid)$")
    from_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    to_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    reason: str = Field(..., min_length=3, max_length=500)
    requires_executive_approval: bool = False


class LeaveReviewRequest(BaseModel):
    decision: str = Field(..., pattern="^(approved|rejected)$")
    decision_note: Optional[str] = Field(default=None, max_length=500)


class AttendanceAdjustRequest(BaseModel):
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern="^(present|absent|on_leave|holiday|weekend)$")
    reason: str = Field(..., min_length=3, max_length=500)


class ImportConfirmRequest(BaseModel):
    duplicate_policy: str = Field(default="skip", pattern="^(skip|update)$")
    duplicate_decisions: Optional[Dict[str, Literal["keep_existing", "update_from_excel"]]] = None
    allow_future_dates: bool = False
