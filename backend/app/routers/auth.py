"""账号接口：注册 / 登录 / 退出 / 我是谁 / 改密码 / 临时票据 / 演示一键登录。

约定：
- 登录成功后返回**明文令牌**（只在这一次响应里出现），前端存 localStorage /
  sessionStorage。
- 第一个注册的账号自动成为**管理员**（单负责人项目的引导方式，日志里会写明）。
- 演示一键登录仅在 `DOCWISE_DEMO_AUTOLOGIN=1` 时可用，且账号必须已存在。
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import (
    clear_login_failures,
    create_session,
    create_ticket,
    hash_password,
    login_block_seconds,
    record_login_failure,
    register_user,
    revoke_session,
    validate_password,
    validate_username,
    verify_password,
)
from ..config import settings
from ..db import get_db
from ..deps import get_current_user, load_owned_task
from ..logging_setup import get_logger
from ..models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = get_logger(__name__)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class PasswordRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class TicketRequest(BaseModel):
    task_id: int
    scope: str = "files"  # files / events


def _serialize_user(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/register", status_code=201)
def register(
    body: RegisterRequest, request: Request, db: Session = Depends(get_db)
) -> dict:
    """注册：第一个账号自动成为管理员。"""
    if (error := validate_username(body.username)) is not None:
        raise HTTPException(status_code=400, detail=error)
    if (error := validate_password(body.password)) is not None:
        raise HTTPException(status_code=400, detail=error)

    existing = db.scalars(
        select(User).where(func.lower(User.username) == body.username.lower())
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="用户名已被占用")

    is_first = db.scalar(select(func.count()).select_from(User)) == 0
    user = register_user(db, body.username, body.password)
    if is_first:
        user.role = "admin"
        db.commit()
        db.refresh(user)
        logger.warning("首个注册账号 %s 已自动设为管理员", user.username)

    token = create_session(db, user, request.headers.get("user-agent"))
    logger.info("新账号注册：%s（管理员=%s）", user.username, user.role == "admin")
    return {"token": token, "user": _serialize_user(user)}


@router.post("/login")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    ip = _client_ip(request)
    blocked = login_block_seconds(body.username, ip)
    if blocked:
        raise HTTPException(
            status_code=429, detail=f"登录失败次数过多，请 {blocked} 秒后再试"
        )

    user = db.scalars(
        select(User).where(func.lower(User.username) == body.username.lower())
    ).first()
    if user is None or not verify_password(body.password, user.password_hash):
        record_login_failure(body.username, ip)
        raise HTTPException(status_code=401, detail="用户名或密码不正确")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被停用，请联系管理员")

    clear_login_failures(body.username, ip)
    user.last_login_at = datetime.now(UTC)
    db.commit()
    token = create_session(db, user, request.headers.get("user-agent"))
    logger.info("登录成功：%s", user.username)
    return {"token": token, "user": _serialize_user(user)}


@router.post("/demo-login")
def demo_login(request: Request, db: Session = Depends(get_db)) -> dict:
    """演示一键登录：仅当 DOCWISE_DEMO_AUTOLOGIN=1 且演示账号存在时可用。"""
    if not settings.docwise_demo_autologin:
        raise HTTPException(status_code=404, detail="演示登录未开启")

    user = db.scalars(
        select(User).where(User.username == settings.docwise_demo_username)
    ).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=404,
            detail=f"演示账号 {settings.docwise_demo_username} 不存在，请先注册",
        )
    token = create_session(db, user, request.headers.get("user-agent"))
    logger.info("演示账号一键登录：%s", user.username)
    return {"token": token, "user": _serialize_user(user)}


@router.post("/logout", status_code=204)
def logout(request: Request, db: Session = Depends(get_db)) -> None:
    header = request.headers.get("authorization") or ""
    token = header[7:].strip() if header.lower().startswith("bearer ") else None
    revoke_session(db, token)
    return None


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return _serialize_user(user)


@router.post("/password", status_code=204)
def change_password(
    body: PasswordRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """改密码：校验旧密码后更新哈希。

    说明：**不改动已有会话**（当前与其他设备都继续有效）——本项目是单负责人内测，
    不做"改密即踢设备"；如需踢掉，用管理后台的停用/重置密码。
    """
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码不正确")
    if (error := validate_password(body.new_password)) is not None:
        raise HTTPException(status_code=400, detail=error)

    user.password_hash = hash_password(body.new_password)
    db.commit()
    logger.info("账号 %s 修改了密码", user.username)
    return None


@router.post("/ticket")
def issue_ticket(
    body: TicketRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """换取临时票据（供进度推送 / PDF 预览 / 下载使用）。先校验任务归属。"""
    load_owned_task(db, user, body.task_id)  # 非本人 404
    if body.scope not in ("files", "events"):
        raise HTTPException(status_code=400, detail="未知票据用途")
    ticket, ttl = create_ticket(db, user, body.task_id, body.scope)
    return {"ticket": ticket, "expires_in": ttl}
