from __future__ import annotations

import datetime
import json
import sqlite3
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.core.config import settings
from app.db.connection import get_connection
from app.schemas.common import RoleEnum

bearer_scheme = HTTPBearer(auto_error=False)

# In-memory revoked token JTI store for server-side logout in MVP
REVOKED_JTIS: set[str] = set()


class AuthenticatedUser(BaseModel):
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
    employment_status: str
    email: Optional[str] = None
    phone: Optional[str] = None
    must_change_password: bool = False
    token_jti: Optional[str] = None


def hash_password(plain_password: str) -> str:
    if len(plain_password) < 6:
        raise ValueError("Mật khẩu phải có ít nhất 6 ký tự.")
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, employee_id: str) -> Tuple[str, str, int]:
    """Create a signed JWT containing only identity claims (role & scope are always loaded fresh from DB)."""
    jti = str(uuid.uuid4())
    now = datetime.datetime.now(datetime.timezone.utc)
    expires_delta = datetime.timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": user_id,
        "emp": employee_id,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, jti, settings.jwt_expire_minutes * 60


def revoke_token(jti: Optional[str]) -> None:
    if jti:
        REVOKED_JTIS.add(jti)


def get_db_dependency():
    """FastAPI dependency yielding a writable SQLite connection; overrideable in pytest."""
    conn = get_connection(readonly=False)
    try:
        yield conn
    finally:
        conn.close()


def load_authenticated_user(conn: sqlite3.Connection, user_id: str, token_jti: Optional[str] = None) -> Optional[AuthenticatedUser]:
    row = conn.execute(
        """
        SELECT
            u.user_id,
            u.username,
            u.is_active,
            u.must_change_password,
            e.employee_id,
            e.full_name,
            e.role,
            e.department_id,
            d.name AS department_name,
            e.position,
            e.manager_id,
            m.full_name AS manager_name,
            e.start_date,
            e.annual_leave_balance,
            e.employment_status,
            e.email,
            e.phone
        FROM users u
        JOIN employees e ON e.employee_id = u.employee_id
        JOIN departments d ON d.department_id = e.department_id
        LEFT JOIN employees m ON m.employee_id = e.manager_id
        WHERE u.user_id = ?
        """,
        (user_id,),
    ).fetchone()

    if not row:
        return None
    if row["is_active"] != 1 or row["employment_status"] != "active":
        return None

    return AuthenticatedUser(
        user_id=row["user_id"],
        username=row["username"],
        employee_id=row["employee_id"],
        full_name=row["full_name"],
        role=RoleEnum(row["role"]),
        department_id=row["department_id"],
        department_name=row["department_name"],
        position=row["position"],
        manager_id=row["manager_id"],
        manager_name=row["manager_name"],
        start_date=row["start_date"],
        annual_leave_balance=float(row["annual_leave_balance"]),
        employment_status=row["employment_status"],
        email=row["email"],
        phone=row["phone"],
        must_change_password=bool(row["must_change_password"]),
        token_jti=token_jti,
    )


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Vui lòng đăng nhập để truy cập hệ thống.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token xác thực không hợp lệ.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    jti = payload.get("jti")
    if jti in REVOKED_JTIS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Phiên đăng nhập đã được đăng xuất.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Thông tin xác thực không hợp lệ.",
        )

    # Always reload role, employee_id, department_id from DB so role/lock changes apply immediately
    user = load_authenticated_user(conn, user_id=user_id, token_jti=jti)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tài khoản không tồn tại hoặc đã bị khóa.",
        )
    return user


def require_roles(*allowed_roles: RoleEnum) -> Callable[[AuthenticatedUser], AuthenticatedUser]:
    allowed_set = set(allowed_roles)

    def _checker(current_user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        if current_user.role not in allowed_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bạn không có quyền thực hiện thao tác hoặc truy cập chức năng này.",
            )
        return current_user

    return _checker


def build_scope_filter(
    user: AuthenticatedUser,
    employee_col: str = "employee_id",
    department_col: str = "department_id",
) -> Tuple[str, List[Any]]:
    """Unified server-side RBAC SQL WHERE filter helper."""
    if user.role == RoleEnum.hr:
        return "1 = 1", []
    if user.role == RoleEnum.manager:
        return f"{department_col} = ?", [user.department_id]
    return f"{employee_col} = ?", [user.employee_id]


def assert_department_access(user: AuthenticatedUser, requested_department_id: Optional[str]) -> Optional[str]:
    """Ensure requested department_id never widens user scope."""
    if not requested_department_id:
        return user.department_id if user.role == RoleEnum.manager else None
    if user.role == RoleEnum.hr:
        return requested_department_id
    if user.role == RoleEnum.manager:
        if requested_department_id != user.department_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Trưởng phòng chỉ được xem dữ liệu thuộc phòng ban mình quản lý.",
            )
        return user.department_id
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Nhân viên không được phép lọc dữ liệu theo phòng ban.",
    )


def assert_employee_access(
    conn: sqlite3.Connection,
    user: AuthenticatedUser,
    target_employee_id: str,
) -> sqlite3.Row:
    target = conn.execute(
        "SELECT employee_id, department_id, role, full_name FROM employees WHERE employee_id = ?",
        (target_employee_id,),
    ).fetchone()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy nhân viên.")
    if user.role == RoleEnum.hr:
        return target
    if user.role == RoleEnum.manager and target["department_id"] == user.department_id:
        return target
    if user.role == RoleEnum.employee and target["employee_id"] == user.employee_id:
        return target
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Bạn không có quyền truy cập dữ liệu của nhân viên này.",
    )


def write_activity_log(
    conn: sqlite3.Connection,
    actor_user_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    before_obj: Optional[Dict[str, Any]] = None,
    after_obj: Optional[Dict[str, Any]] = None,
) -> None:
    conn.execute(
        """
        INSERT INTO activity_logs (actor_user_id, action, entity_type, entity_id, before_json, after_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            actor_user_id,
            action,
            entity_type,
            str(entity_id),
            json.dumps(before_obj, ensure_ascii=False) if before_obj is not None else None,
            json.dumps(after_obj, ensure_ascii=False) if after_obj is not None else None,
        ),
    )
