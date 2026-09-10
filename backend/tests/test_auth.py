"""账号体系测试：注册 / 登录 / 退出 / 改密 / 票据 / 演示登录 / 登录限流。

本文件**不使用** conftest 里的"默认已登录"覆盖（见 conftest.AUTH_TEST_MODULES），
走真实令牌路径。
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from helpers import auth_headers, create_user_row, login, register, upload_pdf

from app import auth as auth_module
from app.config import settings
from app.main import app


@pytest.fixture(autouse=True)
def _clear_login_limits():
    """登录失败计数是进程内的，测试之间必须清掉，避免互相影响。"""
    auth_module._failed_logins.clear()
    yield
    auth_module._failed_logins.clear()


@pytest.fixture
def sample_pdf():
    path = Path(tempfile.gettempdir()) / f"docwise_auth_{uuid.uuid4().hex}.pdf"
    path.write_bytes(b"%PDF-1.4 fake")
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def test_first_registered_user_becomes_admin() -> None:
    with TestClient(app) as client:
        first = register(client, "alice", "password123")
        second = register(client, "bob", "password123")

    assert first["user"]["role"] == "admin"
    assert second["user"]["role"] == "user"


def test_register_validates_username_and_password() -> None:
    with TestClient(app) as client:
        bad_name = client.post(
            "/api/auth/register",
            json={"username": "bad!name", "password": "password123"},
        )
        short_pw = client.post(
            "/api/auth/register", json={"username": "alice", "password": "short"}
        )
        register(client, "alice", "password123")
        duplicate = client.post(
            "/api/auth/register", json={"username": "ALICE", "password": "password123"}
        )

    assert bad_name.status_code == 400
    # 请求体层面的最小长度由 Pydantic 拦下（422），业务层再拦 400
    assert short_pw.status_code in (400, 422)
    assert duplicate.status_code == 409


def test_login_and_me_and_logout() -> None:
    with TestClient(app) as client:
        register(client, "alice", "password123")
        token = login(client, "alice", "password123")

        me = client.get("/api/auth/me", headers=auth_headers(token))
        assert me.status_code == 200
        assert me.json()["username"] == "alice"

        logged_out = client.post("/api/auth/logout", headers=auth_headers(token))
        assert logged_out.status_code == 204
        # 退出后令牌立即失效
        me_after = client.get("/api/auth/me", headers=auth_headers(token))
        assert me_after.status_code == 401


def test_login_wrong_password_then_rate_limited() -> None:
    with TestClient(app) as client:
        register(client, "alice", "password123")
        for _ in range(settings.docwise_login_max_attempts):
            resp = client.post(
                "/api/auth/login", json={"username": "alice", "password": "wrong-pass"}
            )
            assert resp.status_code == 401
        # 超过上限后即使密码正确也被锁
        locked = client.post(
            "/api/auth/login", json={"username": "alice", "password": "password123"}
        )
        assert locked.status_code == 429


def test_change_password() -> None:
    with TestClient(app) as client:
        register(client, "alice", "password123")
        token = login(client, "alice", "password123")

        wrong_old = client.post(
            "/api/auth/password",
            json={"old_password": "nope-nope", "new_password": "newpassword1"},
            headers=auth_headers(token),
        )
        assert wrong_old.status_code == 400

        ok = client.post(
            "/api/auth/password",
            json={"old_password": "password123", "new_password": "newpassword1"},
            headers=auth_headers(token),
        )
        assert ok.status_code == 204
        assert login(client, "alice", "newpassword1")


def test_inactive_user_cannot_login() -> None:
    create_user_row("frozen", "password123", is_active=False)
    with TestClient(app) as client:
        resp = client.post(
            "/api/auth/login", json={"username": "frozen", "password": "password123"}
        )
    assert resp.status_code == 403


def test_ticket_bound_to_task_and_scope(sample_pdf) -> None:
    """票据：只能用于"自己的、指定的那个任务 + 指定用途"。"""
    with TestClient(app) as client:
        alice = register(client, "alice", "password123")["token"]
        task_id = upload_pdf(client, sample_pdf, headers=auth_headers(alice))["id"]

        issued = client.post(
            "/api/auth/ticket",
            json={"task_id": task_id, "scope": "events"},
            headers=auth_headers(alice),
        )
        assert issued.status_code == 200
        ticket = issued.json()["ticket"]

        # 用途对得上：进度推送可以用票据
        with client.stream(
            "GET", f"/api/tasks/{task_id}/events?ticket={ticket}"
        ) as response:
            assert response.status_code == 200

        # 用途对不上（拿 events 票去下文件）→ 401
        assert (
            client.get(f"/api/tasks/{task_id}/files/mono?ticket={ticket}").status_code
            == 401
        )
        # 任务对不上 → 401
        assert (
            client.get(f"/api/tasks/9999/events?ticket={ticket}").status_code == 401
        )
        # 乱写的票据 → 401
        assert (
            client.get(f"/api/tasks/{task_id}/events?ticket=bad-ticket").status_code
            == 401
        )


def test_ticket_requires_task_ownership(sample_pdf) -> None:
    with TestClient(app) as client:
        alice = register(client, "alice", "password123")["token"]
        bob = register(client, "bob", "password123")["token"]
        task_id = upload_pdf(client, sample_pdf, headers=auth_headers(alice))["id"]

        resp = client.post(
            "/api/auth/ticket",
            json={"task_id": task_id, "scope": "files"},
            headers=auth_headers(bob),
        )
    assert resp.status_code == 404


def test_demo_login_disabled_by_default() -> None:
    with TestClient(app) as client:
        assert client.post("/api/auth/demo-login").status_code == 404


def test_demo_login_when_enabled(monkeypatch) -> None:
    create_user_row(settings.docwise_demo_username, "password123")
    monkeypatch.setattr(settings, "docwise_demo_autologin", True)
    with TestClient(app) as client:
        resp = client.post("/api/auth/demo-login")
    assert resp.status_code == 200
    assert resp.json()["user"]["username"] == settings.docwise_demo_username
