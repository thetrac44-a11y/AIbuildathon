from __future__ import annotations

import datetime
import json
import logging
import sqlite3
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple
import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.permissions import get_default_permissions_for_role
from app.db.connection import get_connection, is_postgres_connection
from app.schemas.common import RoleEnum

logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer(auto_error=False)

# Fast in-memory hot cache synchronized with persistent DB table `revoked_tokens`
REVOKED_JTIS: set[str] = set()


def _is_missing_table_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return (
        "no such table" in msg
        or "does not exist" in msg
        or "undefinedtable" in msg
        or exc.__class__.__name__.lower() == "undefinedtable"
    )


def begin_write_transaction(conn: Any) -> None:
    """Acquire an atomic write transaction lock on SQLite (PostgreSQL uses row-level FOR UPDATE)."""
    if is_postgres_connection(conn):
        return
    if not getattr(conn, "in_transaction", False):
        conn.execute("BEGIN IMMEDIATE")


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
    permissions: List[str] = Field(default_factory=list)
    token_jti: Optional[str] = None
    token_exp: Optional[int] = None

    def has_permission(self, permission_code: str) -> bool:
        return permission_code in self.permissions

    def has_any_permission(self, *permission_codes: str) -> bool:
        return any(code in self.permissions for code in permission_codes)


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
    """Create a signed JWT containing only identity claims (role, permissions & scope are always loaded fresh from DB)."""
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


def revoke_token(
    jti: Optional[str],
    conn: Any = None,
    user_id: Optional[str] = None,
    expires_at: Optional[str] = None,
) -> None:
    """Revoke JWT by JTI in both memory cache and persistent DB `revoked_tokens` table."""
    if not jti:
        return
    REVOKED_JTIS.add(jti)
    if conn is None:
        return
    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    try:
        if is_postgres_connection(conn):
            conn.execute(
                """
                INSERT INTO public.revoked_tokens (jti, user_id, expires_at)
                VALUES (?, ?, ?)
                ON CONFLICT (jti) DO NOTHING
                """,
                (jti, user_id, expires_at),
            )
            conn.execute(
                "DELETE FROM public.revoked_tokens WHERE expires_at IS NOT NULL AND expires_at < NOW()"
            )
        else:
            conn.execute(
                """
                INSERT OR IGNORE INTO revoked_tokens (jti, user_id, expires_at)
                VALUES (?, ?, ?)
                """,
                (jti, user_id, expires_at),
            )
            conn.execute(
                "DELETE FROM revoked_tokens WHERE expires_at IS NOT NULL AND expires_at < ?",
                (now_utc,),
            )
    except Exception as exc:
        if _is_missing_table_error(exc):
            if is_postgres_connection(conn):
                conn.rollback()
            logger.warning("revoked_tokens table not initialized yet; falling back to in-memory revocation.")
            return
        logger.exception("Failed to persist token revocation for jti=%s", jti)
        raise


def is_token_revoked(conn: Any, jti: Optional[str]) -> bool:
    """Check whether a JWT JTI has been revoked (checks RAM cache first, then persistent DB)."""
    if not jti:
        return False
    if jti in REVOKED_JTIS:
        return True
    try:
        row = conn.execute("SELECT 1 FROM revoked_tokens WHERE jti = ?", (jti,)).fetchone()
        if row is not None:
            REVOKED_JTIS.add(jti)
            return True
        return False
    except Exception as exc:
        if _is_missing_table_error(exc):
            if is_postgres_connection(conn):
                conn.rollback()
            return False
        logger.exception("Failed checking revoked_tokens for jti=%s", jti)
        raise


def get_db_dependency():
    """FastAPI dependency yielding a writable DB connection; overrideable in pytest."""
    conn = get_connection(readonly=False)
    try:
        yield conn
    finally:
        conn.close()


def load_user_permissions(conn: sqlite3.Connection, user_id: str, role_code: str) -> List[str]:
    """Load effective permission codes strictly from the user's authoritative role in RBAC tables.

    Rules:
    - Authoritative role comes from `employees.role` (`role_code`), NOT an OR-union with stale `user_roles`.
    - When `roles` table is initialized and contains `role_code`, returns the exact mapped permissions
      (including an empty list `[]` if an Admin intentionally revoked all permissions for that role).
    - Only falls back to canonical defaults if the RBAC tables are missing or unseeded (0 role rows).
    """
    try:
        role_row = conn.execute(
            "SELECT role_id FROM roles WHERE role_code = ?",
            (role_code,),
        ).fetchone()
    except Exception as exc:
        if _is_missing_table_error(exc):
            if is_postgres_connection(conn):
                conn.rollback()
            return sorted(get_default_permissions_for_role(role_code))
        logger.exception("Failed querying roles table for role_code=%s", role_code)
        raise

    if role_row is None:
        return sorted(get_default_permissions_for_role(role_code))

    rows = conn.execute(
        """
        SELECT DISTINCT p.permission_code
        FROM role_permissions rp
        JOIN permissions p ON p.permission_id = rp.permission_id
        WHERE rp.role_id = ?
        ORDER BY p.permission_code
        """,
        (role_row["role_id"],),
    ).fetchall()
    return [str(r["permission_code"]) for r in rows]


def sync_user_role_mapping(
    conn: sqlite3.Connection,
    user_id: str,
    role_code: str,
    assigned_by_user_id: Optional[str] = None,
) -> None:
    """Keep user_roles synchronized 1:1 with employees.role whenever an employee/account role changes."""
    try:
        role_row = conn.execute("SELECT role_id FROM roles WHERE role_code = ?", (role_code,)).fetchone()
    except Exception as exc:
        if _is_missing_table_error(exc):
            if is_postgres_connection(conn):
                conn.rollback()
            return
        logger.exception("Failed reading roles during sync_user_role_mapping(user_id=%s)", user_id)
        raise

    if not role_row:
        return

    role_id = role_row["role_id"]
    conn.execute("DELETE FROM user_roles WHERE user_id = ?", (user_id,))
    if is_postgres_connection(conn):
        conn.execute(
            """
            INSERT INTO public.user_roles (user_id, role_id, assigned_by_user_id)
            VALUES (?, ?, ?)
            ON CONFLICT (user_id, role_id) DO NOTHING
            """,
            (user_id, role_id, assigned_by_user_id),
        )
    else:
        conn.execute(
            """
            INSERT OR IGNORE INTO user_roles (user_id, role_id, assigned_by_user_id)
            VALUES (?, ?, ?)
            """,
            (user_id, role_id, assigned_by_user_id),
        )


def load_authenticated_user(
    conn: sqlite3.Connection,
    user_id: str,
    token_jti: Optional[str] = None,
    token_exp: Optional[int] = None,
) -> Optional[AuthenticatedUser]:
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

    role_enum = RoleEnum(row["role"])
    perms = load_user_permissions(conn, row["user_id"], role_enum.value)

    return AuthenticatedUser(
        user_id=row["user_id"],
        username=row["username"],
        employee_id=row["employee_id"],
        full_name=row["full_name"],
        role=role_enum,
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
        permissions=perms,
        token_jti=token_jti,
        token_exp=token_exp,
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
    if is_token_revoked(conn, jti):
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

    # Always reload role, permissions, employee_id, department_id from DB so changes apply immediately
    user = load_authenticated_user(
        conn,
        user_id=user_id,
        token_jti=jti,
        token_exp=payload.get("exp"),
    )
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


def require_permissions(
    *required_permissions: str,
    require_all: bool = False,
) -> Callable[[AuthenticatedUser], AuthenticatedUser]:
    """Permission-based FastAPI authorization dependency.

    When require_all=False (default), grants access if user holds ANY of the listed permissions.
    When require_all=True, requires ALL listed permissions.
    """
    req_list = list(required_permissions)

    def _checker(current_user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        user_perms = set(current_user.permissions)
        allowed = all(p in user_perms for p in req_list) if require_all else any(p in user_perms for p in req_list)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tài khoản của bạn không được cấp quyền (permission) cho chức năng này.",
            )
        return current_user

    return _checker


def build_scope_filter(
    user: AuthenticatedUser,
    employee_col: str = "employee_id",
    department_col: str = "department_id",
) -> Tuple[str, List[Any]]:
    """Unified server-side 5-role RBAC SQL WHERE filter helper.

    - employee  -> own employee_id
    - manager   -> own department_id
    - hr        -> company-wide HR business scope
    - executive -> company-wide read/oversight scope (writes blocked by permission guards)
    - admin     -> system technical scope ONLY; NEVER automatically granted HR business data scope!
    """
    if user.role in (RoleEnum.hr, RoleEnum.executive):
        return "1 = 1", []
    if user.role == RoleEnum.manager:
        return f"{department_col} = ?", [user.department_id]
    if user.role == RoleEnum.employee:
        return f"{employee_col} = ?", [user.employee_id]
    # Admin: Technical Administration ONLY — must explicitly be blocked from HR business data queries
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Vai trò Quản trị hệ thống (Admin) không mặc định có quyền truy cập dữ liệu nghiệp vụ nhân sự.",
    )


def resolve_ai_effective_scope(user: AuthenticatedUser) -> str:
    """Authoritative AI data scope computed strictly as the intersection of user.role and DB permissions.

    Guarantees:
    - admin     -> ALWAYS 'none' (Technical Admin has NO HR AI business scope, even if misconfigured).
    - employee  -> max 'self' (never elevated above 'self' even if wider ai.ask.* permission is misassigned).
    - manager   -> 'department' if holding ai.ask.department/all/strategy; 'self' if narrowed to ai.ask.self.
    - hr        -> 'all' if holding ai.ask.all/strategy; 'department' if narrowed; 'self' if narrowed.
    - executive -> 'all' if holding ai.ask.all/strategy; 'department' if narrowed; 'self' if narrowed.
    - Anyone with zero AI permissions -> 'none'.
    """
    if user.role == RoleEnum.admin:
        return "none"
    perms = set(user.permissions)
    if not (perms & {"ai.ask.self", "ai.ask.department", "ai.ask.all", "ai.strategy"}):
        return "none"
    if user.role == RoleEnum.employee:
        return "self"
    if user.role == RoleEnum.manager:
        if perms & {"ai.ask.department", "ai.ask.all", "ai.strategy"}:
            return "department"
        return "self"
    # HR & Executive: enforce dynamic permission narrowing configured in DB RBAC matrix
    if perms & {"ai.ask.all", "ai.strategy"}:
        return "all"
    if "ai.ask.department" in perms:
        return "department"
    return "self"


def build_ai_scope_filter(
    user: AuthenticatedUser,
    employee_col: str = "employee_id",
    department_col: str = "department_id",
    force_self: bool = False,
) -> Tuple[str, List[Any]]:
    """Server-side AI SQL WHERE scope filter strictly bound to EffectiveScopeResolver (role ∩ permissions)."""
    scope = resolve_ai_effective_scope(user)
    if scope == "none":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản hiện tại không có quyền truy vấn dữ liệu nghiệp vụ nhân sự qua Trợ lý AI.",
        )
    if force_self or scope == "self":
        return f"{employee_col} = ?", [user.employee_id]
    if scope == "department":
        return f"{department_col} = ?", [user.department_id]
    return "1 = 1", []


def assert_department_access(user: AuthenticatedUser, requested_department_id: Optional[str]) -> Optional[str]:
    """Ensure requested department_id never widens user scope across all 5 roles."""
    if user.role == RoleEnum.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Quản trị hệ thống (Admin) không mặc định truy cập dữ liệu nghiệp vụ theo phòng ban.",
        )
    if not requested_department_id:
        return user.department_id if user.role == RoleEnum.manager else None
    if user.role in (RoleEnum.hr, RoleEnum.executive):
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
    if user.role in (RoleEnum.hr, RoleEnum.executive):
        return target
    if user.role == RoleEnum.manager and target["department_id"] == user.department_id:
        return target
    if user.role == RoleEnum.employee and target["employee_id"] == user.employee_id:
        return target
    # Admin only sees own self-profile via /api/profile, NOT other employees' HR business records
    if user.role == RoleEnum.admin and target["employee_id"] == user.employee_id:
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
