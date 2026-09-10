"""管理后台接口（管理员专用）：用户总览、任务总览、重置密码、停用启用、角色调整。

最小范围：够用即止——不做权限分组、不做操作审计、不做数据看板。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import hash_password, validate_password
from ..db import get_db
from ..deps import require_admin
from ..logging_setup import get_logger
from ..models import Task, User

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = get_logger(__name__)


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class ActiveRequest(BaseModel):
    is_active: bool


class RoleRequest(BaseModel):
    role: str = Field(pattern="^(user|admin)$")


def _serialize_user_row(user: User, task_count: int) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "task_count": task_count,
    }


@router.get("/users")
def list_users(
    db: Session = Depends(get_db), _admin: User = Depends(require_admin)
) -> list[dict]:
    """全部账号 + 各自任务数（新账号在前）。"""
    rows = db.execute(
        select(User, func.count(Task.id))
        .outerjoin(Task, Task.user_id == User.id)
        .group_by(User.id)
        .order_by(User.id.desc())
    ).all()
    return [_serialize_user_row(user, count) for user, count in rows]


@router.get("/tasks")
def list_tasks(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
    user_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """全部用户的任务总览（可按用户、状态筛选）。"""
    query = (
        select(Task, User.username)
        .outerjoin(User, User.id == Task.user_id)
        .order_by(Task.id.desc())
        .limit(max(1, min(limit, 500)))
    )
    if user_id is not None:
        query = query.where(Task.user_id == user_id)
    if status:
        query = query.where(Task.status == status)

    return [
        {
            "id": task.id,
            "filename": task.filename,
            "status": task.status,
            "tier": task.tier,
            "progress": task.progress,
            "owner": username or "（无主）",
            "owner_id": task.user_id,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "error_message": task.error_message,
        }
        for task, username in db.execute(query).all()
    ]


@router.post("/users/{user_id}/password", status_code=204)
def reset_password(
    user_id: int,
    body: ResetPasswordRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> None:
    """重置某账号密码（本项目不做邮箱找回，忘记密码找管理员）。"""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    if (error := validate_password(body.new_password)) is not None:
        raise HTTPException(status_code=400, detail=error)

    user.password_hash = hash_password(body.new_password)
    db.commit()
    logger.warning("管理员重置了账号 %s 的密码", user.username)
    return None


@router.post("/users/{user_id}/active", status_code=204)
def set_active(
    user_id: int,
    body: ActiveRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> None:
    """停用 / 启用账号（管理员不能停用自己，避免把自己锁在外面）。"""
    if user_id == admin.id and not body.is_active:
        raise HTTPException(status_code=400, detail="不能停用当前登录的管理员账号")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="账号不存在")

    user.is_active = body.is_active
    db.commit()
    logger.warning(
        "管理员 %s 把账号 %s 设为 %s",
        admin.username,
        user.username,
        "启用" if body.is_active else "停用",
    )
    return None


@router.post("/users/{user_id}/role", status_code=204)
def set_role(
    user_id: int,
    body: RoleRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> None:
    """调整角色（管理员不能给自己降级，避免没有管理员）。"""
    if user_id == admin.id and body.role != "admin":
        raise HTTPException(status_code=400, detail="不能取消当前登录账号的管理员身份")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="账号不存在")

    user.role = body.role
    db.commit()
    logger.warning(
        "管理员 %s 把账号 %s 的角色改为 %s", admin.username, user.username, body.role
    )
    return None
