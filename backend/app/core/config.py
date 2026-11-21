import os
from typing import List
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseModel):
    app_name: str = os.getenv("APP_NAME", "HR Attendance Copilot API")
    app_env: str = os.getenv("APP_ENV", "development")
    version: str = "1.0.0"
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./hr_attendance.db")
    allow_manager_employee_read: bool = os.getenv("ALLOW_MANAGER_EMPLOYEE_READ", "true").lower() == "true"
    cors_origins: List[str] = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
        if origin.strip()
    ]

    # Business rules from PDF specification
    work_start_time: str = "08:30:00"
    work_end_time: str = "17:30:00"
    lunch_break_hours: float = 1.0
    standard_work_hours: float = 8.0
    late_grace_minutes: int = 5
    ai_query_timeout_seconds: int = 3
    ai_query_max_rows: int = 200


settings = Settings()
