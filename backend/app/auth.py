"""账号体系核心逻辑（**纯逻辑、无路由**，便于单测）。

包含：密码哈希 / 会话令牌 / 临时票据 / 登录限流。

设计取舍：
- **密码**：标准库 `hashlib.scrypt` + 每人独立随机盐，不引额外依赖（也避免动 uv.lock），
  绝不明文、绝不用 MD5/SHA1。
- **会话**：随机不透明令牌（`secrets.token_urlsafe`），库里只存 sha256；
  比 JWT 简单，且可立即吊销。
- **票据**：给 EventSource / iframe / <a download> 用（这三种浏览器请求带不了请求头），
  绑定「用户 + 任务 + 用途」，60 秒有效。
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import settings
from .models import AuthSession, AuthTicket, User

# scrypt 参数（识别串里会带上，便于以后升级参数仍能校验老密码）
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_KEY_LEN = 32

TICKET_TTL_SECONDS = 60
LOGIN_LOCK_SECONDS = 300
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
MIN_PASSWORD_LENGTH = 8

# 登录失败计数（进程内即可：单进程部署；键 = 用户名 + IP）
_failed_logins: dict[str, list[float]] = {}


# ---------------------------------------------------------------- 密码
def hash_password(password: str) -> str:
    """返回 `scrypt$n$r$p$salt_hex$key_hex`（盐随机，每人不同）。"""
    salt = secrets.token_bytes(_SALT_BYTES)
    key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_KEY_LEN,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验密码；存储串损坏时返回 False（不抛异常）。"""
    try:
        algo, n, r, p, salt_hex, key_hex = stored.split("$")
        if algo != "scrypt":
            return False
        key = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(key_hex)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(key.hex(), key_hex)


def validate_username(username: str) -> str | None:
    if USERNAME_RE.match(username or ""):
        return None
    return "用户名需 3–32 位，仅限字母/数字/下划线/点/短横线"


def validate_password(password: str) -> str | None:
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        return f"密码至少 {MIN_PASSWORD_LENGTH} 位"
    return None


# ---------------------------------------------------------------- 会话
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, user: User, user_agent: str | None = None) -> str:
    """签发会话，返回**明文令牌**（只在这一刻存在于响应里，库里只存哈希）。"""
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    db.add(
        AuthSession(
            token_hash=_hash_token(token),
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(days=settings.docwise_session_days),
            last_seen_at=now,
            user_agent=(user_agent or "")[:255] or None,
        )
    )
    db.commit()
    return token


def resolve_session(db: Session, token: str | None) -> User | None:
    """令牌 → 用户；过期/停用/不存在都返回 None。命中时滑动续期。"""
    if not token:
        return None
    session = db.scalars(
        select(AuthSession).where(AuthSession.token_hash == _hash_token(token))
    ).first()
    if session is None:
        return None
    now = datetime.now(UTC)
    if session.expires_at.replace(tzinfo=UTC) <= now:
        db.delete(session)
        db.commit()
        return None
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None

    session.last_seen_at = now
    full = timedelta(days=settings.docwise_session_days)
    # 剩余不足一半有效期就续一次，避免每个请求都写库
    if (session.expires_at.replace(tzinfo=UTC) - now) < full / 2:
        session.expires_at = now + full
    db.commit()
    return user


def revoke_session(db: Session, token: str | None) -> None:
    if not token:
        return
    db.execute(delete(AuthSession).where(AuthSession.token_hash == _hash_token(token)))
    db.commit()


def revoke_all_sessions(db: Session, user_id: int) -> None:
    db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
    db.commit()


# ------------------------------------------------ 票据（进度推送 / 预览 / 下载）
def create_ticket(db: Session, user: User, task_id: int, scope: str) -> tuple[str, int]:
    """签发 60 秒票据（绑定用户+任务+用途）；返回 (明文票据, 有效秒数)。"""
    if scope not in ("files", "events"):
        raise ValueError("未知票据用途")
    ticket = secrets.token_urlsafe(24)
    now = datetime.now(UTC)
    db.add(
        AuthTicket(
            ticket_hash=_hash_token(ticket),
            user_id=user.id,
            task_id=task_id,
            scope=scope,
            created_at=now,
            expires_at=now + timedelta(seconds=TICKET_TTL_SECONDS),
        )
    )
    db.commit()
    return ticket, TICKET_TTL_SECONDS


def resolve_ticket(
    db: Session, ticket: str | None, task_id: int, scope: str
) -> User | None:
    """票据 → 用户；必须**任务与用途都对得上**且未过期。"""
    if not ticket:
        return None
    row = db.scalars(
        select(AuthTicket).where(AuthTicket.ticket_hash == _hash_token(ticket))
    ).first()
    if row is None or row.task_id != task_id or row.scope != scope:
        return None
    if row.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC):
        db.delete(row)
        db.commit()
        return None
    user = db.get(User, row.user_id)
    return user if user is not None and user.is_active else None


def purge_expired(db: Session) -> int:
    """清理过期会话与票据（启动时调一次即可）。"""
    now = datetime.now(UTC)
    removed = db.execute(
        delete(AuthSession).where(AuthSession.expires_at <= now)
    ).rowcount or 0
    removed += db.execute(
        delete(AuthTicket).where(AuthTicket.expires_at <= now)
    ).rowcount or 0
    db.commit()
    return removed


# ---------------------------------------------------------------- 用户 / 登录限流
def register_user(db: Session, username: str, password: str) -> User:
    """注册（校验交给路由层先做）；用户名重复由 unique 约束兜底。"""
    user = User(username=username, password_hash=hash_password(password), role="user")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _login_key(username: str, client_ip: str | None) -> str:
    return f"{username.lower()}@{client_ip or '-'}"


def login_block_seconds(username: str, client_ip: str | None) -> int:
    """被锁则返回剩余秒数（>0），否则 0。超过时间窗自动放行。"""
    key = _login_key(username, client_ip)
    now = time.monotonic()
    attempts = [t for t in _failed_logins.get(key, []) if now - t < LOGIN_LOCK_SECONDS]
    _failed_logins[key] = attempts
    if len(attempts) >= settings.docwise_login_max_attempts:
        return max(1, int(LOGIN_LOCK_SECONDS - (now - attempts[-1])))
    return 0


def record_login_failure(username: str, client_ip: str | None) -> None:
    key = _login_key(username, client_ip)
    _failed_logins.setdefault(key, []).append(time.monotonic())


def clear_login_failures(username: str, client_ip: str | None) -> None:
    _failed_logins.pop(_login_key(username, client_ip), None)
