"""管理后台测试：管理员可用；普通用户一律 403；重置密码/停用/角色生效。

本文件不使用 conftest 的"默认已登录"覆盖，走真实令牌。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import auth_headers, create_user_row, login, register

from app.db import SessionLocal
from app.main import app
from app.models import Task


def test_admin_can_list_users_and_tasks() -> None:
    with TestClient(app) as client:
        # 第一个注册的账号才是管理员，所以先建管理员，再建其他账号
        admin = register(client, "admin", "password123")["token"]
        owner_id = create_user_row("alice", "password123")
        with SessionLocal() as session:
            session.add(Task(user_id=owner_id, filename="a.pdf", status="completed"))
            session.commit()

        headers = auth_headers(admin)

        users = client.get("/api/admin/users", headers=headers)
        assert users.status_code == 200
        names = {row["username"] for row in users.json()}
        assert {"alice", "admin"} <= names
        alice_row = next(r for r in users.json() if r["username"] == "alice")
        assert alice_row["task_count"] == 1

        tasks = client.get("/api/admin/tasks", headers=headers)
        assert tasks.status_code == 200
        assert tasks.json()[0]["owner"] == "alice"


def test_admin_routes_require_admin_role() -> None:
    with TestClient(app) as client:
        register(client, "admin", "password123")  # 首个账号成为管理员
        user = register(client, "bob", "password123")["token"]
        headers = auth_headers(user)

        cases = [
            ("GET", "/api/admin/users", {}),
            ("GET", "/api/admin/tasks", {}),
            ("POST", "/api/admin/users/1/password", {"json": {"new_password": "x1234567"}}),  # noqa: E501
            ("POST", "/api/admin/users/1/active", {"json": {"is_active": False}}),
            ("POST", "/api/admin/users/1/role", {"json": {"role": "admin"}}),
        ]
        for method, url, kwargs in cases:
            resp = client.request(method, url, headers=headers, **kwargs)
            assert resp.status_code == 403, (
                f"{method} {url} 应为 403，实际 {resp.status_code}"
            )


def test_admin_resets_password_and_user_can_login_with_it() -> None:
    with TestClient(app) as client:
        admin = register(client, "admin", "password123")["token"]
        user_id = create_user_row("alice", "oldpassword1")
        resp = client.post(
            f"/api/admin/users/{user_id}/password",
            json={"new_password": "brandnew123"},
            headers=auth_headers(admin),
        )
        assert resp.status_code == 204
        assert login(client, "alice", "brandnew123")


def test_admin_activates_and_deactivates_user() -> None:
    with TestClient(app) as client:
        admin = register(client, "admin", "password123")["token"]
        user_id = create_user_row("alice", "password123")
        headers = auth_headers(admin)

        off = client.post(
            f"/api/admin/users/{user_id}/active",
            json={"is_active": False},
            headers=headers,
        )
        assert off.status_code == 204
        blocked = client.post(
            "/api/auth/login", json={"username": "alice", "password": "password123"}
        )
        assert blocked.status_code == 403

        on = client.post(
            f"/api/admin/users/{user_id}/active",
            json={"is_active": True},
            headers=headers,
        )
        assert on.status_code == 204
        assert login(client, "alice", "password123")


def test_admin_cannot_disable_or_demote_self() -> None:
    with TestClient(app) as client:
        admin = register(client, "admin", "password123")
        headers = auth_headers(admin["token"])
        admin_id = admin["user"]["id"]

        assert (
            client.post(
                f"/api/admin/users/{admin_id}/active",
                json={"is_active": False},
                headers=headers,
            ).status_code
            == 400
        )
        assert (
            client.post(
                f"/api/admin/users/{admin_id}/role",
                json={"role": "user"},
                headers=headers,
            ).status_code
            == 400
        )


def test_admin_can_promote_user() -> None:
    with TestClient(app) as client:
        admin = register(client, "admin", "password123")["token"]
        user_id = create_user_row("alice", "password123")
        resp = client.post(
            f"/api/admin/users/{user_id}/role",
            json={"role": "admin"},
            headers=auth_headers(admin),
        )
        assert resp.status_code == 204
        # 提升后 alice 也能访问后台
        alice = login(client, "alice", "password123")
        assert (
            client.get("/api/admin/users", headers=auth_headers(alice)).status_code
            == 200
        )
