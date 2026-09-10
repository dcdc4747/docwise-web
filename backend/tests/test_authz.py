"""权限测试：未登录一律 401；跨用户访问一律 404（不暴露"存在但无权限"）。

本文件不使用 conftest 的"默认已登录"覆盖，走真实令牌。
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from helpers import auth_headers, register, upload_pdf

from app.auth import hash_password
from app.db import SessionLocal
from app.main import app
from app.models import Task, TaskBlock


@pytest.fixture
def sample_pdf():
    path = Path(tempfile.gettempdir()) / f"docwise_authz_{uuid.uuid4().hex}.pdf"
    path.write_bytes(b"%PDF-1.4 fake")
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def _make_task(owner_username: str, filename: str = "a.pdf") -> int:
    """给指定账号直接建一个任务（带一个块，便于测问答/导读接口）。"""
    with SessionLocal() as session:
        from app.models import User

        owner = session.query(User).filter(User.username == owner_username).one()
        task = Task(
            user_id=owner.id, filename=filename, status="completed", progress=1.0
        )
        session.add(task)
        session.flush()
        session.add(
            TaskBlock(task_id=task.id, block_id="b1", text="hello", translated="你好")
        )
        session.commit()
        return task.id


def test_protected_routes_require_login(sample_pdf) -> None:
    """未登录：所有需要身份的接口都必须是 401。"""
    with TestClient(app) as client:
        task_id = 1
        cases = [
            ("GET", "/api/tasks", {}),
            ("GET", f"/api/tasks/{task_id}", {}),
            ("GET", f"/api/tasks/{task_id}/files/mono", {}),
            ("GET", f"/api/tasks/{task_id}/events", {}),
            ("GET", f"/api/tasks/{task_id}/understanding", {}),
            ("POST", f"/api/tasks/{task_id}/understanding", {}),
            ("POST", f"/api/tasks/{task_id}/ask", {"json": {"question": "hi"}}),
            ("POST", "/api/tasks/upload", {}),
            ("POST", "/api/auth/ticket", {"json": {"task_id": 1, "scope": "files"}}),
            ("GET", "/api/auth/me", {}),
            ("GET", "/api/admin/users", {}),
        ]
        for method, url, kwargs in cases:
            resp = client.request(method, url, **kwargs)
            assert resp.status_code == 401, (
                f"{method} {url} 应为 401，实际 {resp.status_code}"
            )

    # 公开接口不受影响
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200


def test_cross_user_access_returns_404() -> None:
    with TestClient(app) as client:
        register(client, "alice", "password123")
        bob = register(client, "bob", "password123")["token"]
        task_id = _make_task("alice")

        headers = auth_headers(bob)
        cases = [
            ("GET", f"/api/tasks/{task_id}", {}),
            ("GET", f"/api/tasks/{task_id}/files/mono", {}),
            ("GET", f"/api/tasks/{task_id}/events", {}),
            ("GET", f"/api/tasks/{task_id}/understanding", {}),
            ("POST", f"/api/tasks/{task_id}/understanding", {}),
            ("POST", f"/api/tasks/{task_id}/ask", {"json": {"question": "hi"}}),
        ]
        for method, url, kwargs in cases:
            resp = client.request(method, url, headers=headers, **kwargs)
            assert resp.status_code == 404, (
                f"{method} {url} 应为 404，实际 {resp.status_code}"
            )


def test_task_list_only_returns_own_tasks() -> None:
    with TestClient(app) as client:
        alice = register(client, "alice", "password123")["token"]
        bob = register(client, "bob", "password123")["token"]
        _make_task("alice", "alice.pdf")
        _make_task("bob", "bob.pdf")

        alice_names = [
            t["filename"]
            for t in client.get("/api/tasks", headers=auth_headers(alice)).json()
        ]
        bob_names = [
            t["filename"]
            for t in client.get("/api/tasks", headers=auth_headers(bob)).json()
        ]

    assert alice_names == ["alice.pdf"]
    assert bob_names == ["bob.pdf"]


def test_owner_can_access_own_task(sample_pdf) -> None:
    """反向确认：自己的任务必须能正常访问（否则上面那些 404 可能是"全都坏了"）。"""
    with TestClient(app) as client:
        alice = register(client, "alice", "password123")["token"]
        task_id = upload_pdf(client, sample_pdf, headers=auth_headers(alice))["id"]
        headers = auth_headers(alice)

        assert client.get(f"/api/tasks/{task_id}", headers=headers).status_code == 200
        # 文件尚未产出 → 404（但这是"文件不存在"而非"无权限"）
        assert (
            client.get(f"/api/tasks/{task_id}/files/mono", headers=headers).status_code
            == 404
        )


def test_disabled_user_token_rejected() -> None:
    """账号被停用后，手里的旧令牌立即失效。"""
    with SessionLocal() as session:
        from app.models import User

        user = User(username="frozen", password_hash=hash_password("password123"))
        session.add(user)
        session.commit()
        user_id = user.id

    with TestClient(app) as client:
        token = client.post(
            "/api/auth/login", json={"username": "frozen", "password": "password123"}
        ).json()["token"]
        assert (
            client.get("/api/auth/me", headers=auth_headers(token)).status_code == 200
        )

        with SessionLocal() as session:
            from app.models import User

            session.get(User, user_id).is_active = False
            session.commit()

        assert (
            client.get("/api/auth/me", headers=auth_headers(token)).status_code == 401
        )
