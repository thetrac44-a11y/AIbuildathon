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
    jwt_secret_key: str = os.getenv(
        "JWT_SECRET_KEY",
        "dev-only-jwt-secret-key-change-in-production-32bytes",
    )
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))
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

    def validate_runtime_security(self) -> None:
        """Refuse insecure startup in production with default/short JWT secret."""
        if self.app_env.lower() == "production":
            if (
                len(self.jwt_secret_key) < 32
                or self.jwt_secret_key.startswith("dev-only")
                or self.jwt_secret_key.startswith("change-this")
            ):
                raise RuntimeError(
                    "SECURITY ERROR: JWT_SECRET_KEY phải được cấu hình riêng tối thiểu 32 ký tự khi APP_ENV=production."
                )


settings = Settings()
