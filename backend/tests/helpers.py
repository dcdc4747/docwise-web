"""测试共用常量与小工具。

每个测试的库里都会重建这两个账号（见 conftest._reset_db）：

- `TEST_USER_ID` / `TEST_USERNAME`：普通用户，也是"默认已登录"的身份；
- `TEST_ADMIN_ID`：管理员。

测试里直接建任务时请带上 `user_id=TEST_USER_ID`，否则按归属过滤后查不到。
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import hash_password
from app.db import SessionLocal
from app.models import User

TEST_USER_ID = 1
TEST_ADMIN_ID = 2
TEST_USERNAME = "tester"


def upload_pdf(
    client: TestClient,
    path: Path,
    tier: str = "fast",
    headers: dict[str, str] | None = None,
) -> dict:
    """通过上传接口建任务（202 即成功），返回任务卡。

    鉴权测试里必须传 `headers=auth_headers(token)`（这些测试没有"默认已登录"覆盖）。
    """
    with path.open("rb") as handle:
        resp = client.post(
            "/api/tasks/upload",
            files={"file": (path.name, handle, "application/pdf")},
            data={"tier": tier},
            headers=headers or {},
        )
    assert resp.status_code == 202, resp.text
    return resp.json()


def register(client: TestClient, username: str, password: str) -> dict:
    """注册（首个账号会自动成为管理员）；返回 {token, user}。"""
    resp = client.post(
        "/api/auth/register", json={"username": username, "password": password}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def login(client: TestClient, username: str, password: str) -> str:
    """登录并返回令牌。"""
    resp = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_user_row(
    username: str, password: str, role: str = "user", is_active: bool = True
) -> int:
    """直接入库建账号（用于需要"已存在账号"的测试，如管理后台重置密码）。"""
    with SessionLocal() as session:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            is_active=is_active,
        )
        session.add(user)
        session.commit()
        return user.id
