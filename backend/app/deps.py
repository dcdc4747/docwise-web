"""集中依赖注入与访问守卫。

- `get_db` / `get_settings`：从 db/config 再导出，保持单一实现。
- `get_current_user`：普通接口只认 `Authorization: Bearer <令牌>`。
- `get_user_for_files` / `get_user_for_events`：进度推送、PDF 预览、文件下载这三种
  浏览器请求带不了自定义请求头，所以额外接受 `?ticket=`（绑定 用户+任务+用途，60 秒）。
- `load_owned_task`：取任务并校验归属，非本人一律 404（不暴露"存在但无权限"）。
- `require_admin`：管理后台专用。
"""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .auth import resolve_session, resolve_ticket
from .config import Settings, settings
from .db import SessionLocal, get_db
from .models import Task, User

__all__ = [
    "Settings",
    "SessionLocal",
    "get_current_user",
    "get_db",
    "get_settings",
    "get_user_for_events",
    "get_user_for_files",
    "load_owned_task",
    "require_admin",
    "settings",
]


def get_settings() -> Settings:
    return settings


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = resolve_session(db, _bearer_token(request))
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="未登录或登录已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def _user_for_task(request: Request, db: Session, task_id: int, scope: str) -> User:
    user = resolve_session(db, _bearer_token(request))
    if user is None:
        user = resolve_ticket(db, request.query_params.get("ticket"), task_id, scope)
    if user is None:
        raise HTTPException(status_code=401, detail="未登录，或票据无效/已过期")
    return user


def get_user_for_files(
    request: Request, task_id: int, db: Session = Depends(get_db)
) -> User:
    """文件预览 / 下载：接受 Bearer，或 files 用途的票据。"""
    return _user_for_task(request, db, task_id, "files")


def get_user_for_events(
    request: Request, task_id: int, db: Session = Depends(get_db)
) -> User:
    """进度推送（SSE）：接受 Bearer，或 events 用途的票据。"""
    return _user_for_task(request, db, task_id, "events")


def load_owned_task(db: Session, user: User, task_id: int) -> Task:
    """取任务并校验归属；非本人（或不存在）一律 404。"""
    task = db.get(Task, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="task not found")
    return task


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
