from __future__ import annotations

import datetime
import sqlite3
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.routes import build_screens
from app.core.config import settings
from app.core.security import (
    AuthenticatedUser,
    create_access_token,
    get_current_user,
    get_db_dependency,
    hash_password,
    load_authenticated_user,
    revoke_token,
    verify_password,
    write_activity_log,
)
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    SelfProfileUpdateRequest,
    UserProfileResponse,
)

router = APIRouter(prefix="/api", tags=["auth"])


def _build_profile_response(conn: sqlite3.Connection, user: AuthenticatedUser) -> UserProfileResponse:
    used_row = conn.execute(
        """
        SELECT COALESCE(SUM(leave_days), 0) AS used_days
        FROM v_leave_requests
        WHERE employee_id = ? AND leave_type = 'annual' AND status = 'approved'
        """,
        (user.employee_id,),
    ).fetchone()
    used_days = float(used_row["used_days"]) if used_row else 0.0
    remaining_days = max(0.0, round(user.annual_leave_balance - used_days, 2))

    screens = build_screens(settings.allow_manager_employee_read)
    user_perms = set(user.permissions)
    allowed_screens = []
    for s in screens:
        if s.permission:
            if s.permission in user_perms:
                allowed_screens.append(s.id)
        elif s.any_permissions:
            if any(p in user_perms for p in s.any_permissions):
                allowed_screens.append(s.id)
        elif user.role in s.allowed_roles:
            allowed_screens.append(s.id)

    return UserProfileResponse(
        user_id=user.user_id,
        username=user.username,
        employee_id=user.employee_id,
        full_name=user.full_name,
        role=user.role,
        department_id=user.department_id,
        department_name=user.department_name,
        position=user.position,
        manager_id=user.manager_id,
        manager_name=user.manager_name,
        start_date=user.start_date,
        annual_leave_balance=user.annual_leave_balance,
        used_annual_leave=used_days,
        remaining_annual_leave=remaining_days,
        employment_status=user.employment_status,
        email=user.email,
        phone=user.phone,
        must_change_password=user.must_change_password,
        permissions=sorted(user_perms),
        allowed_screens=allowed_screens,
    )


@router.post("/auth/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> LoginResponse:
    username = payload.username.strip().lower()
    row = conn.execute(
        """
        SELECT u.user_id, u.username, u.password_hash, u.employee_id, u.is_active, e.employment_status
        FROM users u
        JOIN employees e ON e.employee_id = u.employee_id
        WHERE LOWER(u.username) = ?
        """,
        (username,),
    ).fetchone()

    if not row or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tên đăng nhập hoặc mật khẩu không chính xác.",
        )

    if row["is_active"] != 1 or row["employment_status"] != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản đã bị khóa hoặc nhân viên đã ngừng hoạt động.",
        )

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE users SET last_login_at = ? WHERE user_id = ?", (now_str, row["user_id"]))
    write_activity_log(
        conn,
        actor_user_id=row["user_id"],
        action="login_success",
        entity_type="user",
        entity_id=row["user_id"],
        after_obj={"username": row["username"], "login_at": now_str},
    )
    conn.commit()

    token, jti, expires_in = create_access_token(row["user_id"], row["employee_id"])
    user = load_authenticated_user(conn, row["user_id"], token_jti=jti)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Không thể tải thông tin tài khoản.")

    return LoginResponse(
        access_token=token,
        expires_in=expires_in,
        user=_build_profile_response(conn, user),
    )


@router.post("/auth/logout")
def logout(
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db_dependency),
):
    revoke_token(current_user.token_jti)
    write_activity_log(
        conn,
        actor_user_id=current_user.user_id,
        action="logout",
        entity_type="user",
        entity_id=current_user.user_id,
    )
    conn.commit()
    return {"status": "ok", "message": "Đăng xuất thành công."}


@router.get("/auth/me", response_model=UserProfileResponse)
def get_me(
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> UserProfileResponse:
    return _build_profile_response(conn, current_user)


@router.post("/auth/change-password")
def change_password(
    payload: ChangePasswordRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db_dependency),
):
    row = conn.execute(
        "SELECT password_hash FROM users WHERE user_id = ?",
        (current_user.user_id,),
    ).fetchone()
    if not row or not verify_password(payload.current_password, row["password_hash"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mật khẩu hiện tại không đúng.")

    new_hash = hash_password(payload.new_password)
    conn.execute(
        "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE user_id = ?",
        (new_hash, current_user.user_id),
    )
    write_activity_log(
        conn,
        actor_user_id=current_user.user_id,
        action="change_password",
        entity_type="user",
        entity_id=current_user.user_id,
    )
    conn.commit()
    return {"status": "ok", "message": "Đổi mật khẩu thành công."}


@router.get("/profile", response_model=UserProfileResponse)
def get_profile(
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> UserProfileResponse:
    return _build_profile_response(conn, current_user)


@router.patch("/profile", response_model=UserProfileResponse)
def update_self_profile(
    payload: SelfProfileUpdateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db_dependency),
) -> UserProfileResponse:
    """Only safe contact fields (phone) can be updated by the user. Role/department/balance are forbidden."""
    before_obj = {"phone": current_user.phone}
    conn.execute(
        "UPDATE employees SET phone = ? WHERE employee_id = ?",
        (payload.phone, current_user.employee_id),
    )
    write_activity_log(
        conn,
        actor_user_id=current_user.user_id,
        action="update_self_profile",
        entity_type="employee",
        entity_id=current_user.employee_id,
        before_obj=before_obj,
        after_obj={"phone": payload.phone},
    )
    conn.commit()
    refreshed = load_authenticated_user(conn, current_user.user_id, current_user.token_jti)
    assert refreshed is not None
    return _build_profile_response(conn, refreshed)
