"""阅读位置记忆：记住读到第几页，让「继续读」真的接着读。

形态要求（docs/产品形态说明.md）：L1 卡片显示「上次读到第 X 页」，进来跳回原处；
**没有记录时显示「开始阅读」而不是「继续读」**——不假装记得。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import TEST_USER_ID

from app.db import SessionLocal
from app.main import app
from app.models import Task


def _make_task() -> int:
    with SessionLocal() as session:
        task = Task(user_id=TEST_USER_ID, filename="a.pdf", status="completed")
        session.add(task)
        session.commit()
        return task.id


def test_reading_position_defaults_to_none() -> None:
    """没读过就是 null —— 前端据此显示「开始阅读」。"""
    task_id = _make_task()
    with TestClient(app) as client:
        res = client.get(f"/api/tasks/{task_id}")

    assert res.status_code == 200
    assert res.json()["last_read_page"] is None


def test_save_and_read_back_position() -> None:
    task_id = _make_task()
    with TestClient(app) as client:
        saved = client.post(f"/api/tasks/{task_id}/reading-position", json={"page": 5})
        detail = client.get(f"/api/tasks/{task_id}")

    assert saved.status_code == 200
    assert saved.json()["last_read_page"] == 5
    assert detail.json()["last_read_page"] == 5


def test_list_tasks_also_carries_position() -> None:
    """列表也要带（L1 卡片要显示「上次读到第 X 页」，不该为每张卡再请求一次详情）。"""
    task_id = _make_task()
    with TestClient(app) as client:
        client.post(f"/api/tasks/{task_id}/reading-position", json={"page": 3})
        rows = client.get("/api/tasks").json()

    target = [row for row in rows if row["id"] == task_id]
    assert target and target[0]["last_read_page"] == 3


def test_reading_position_validates_page() -> None:
    """页码得是正经页码：0 和负数直接 422，不写进库。"""
    task_id = _make_task()
    with TestClient(app) as client:
        bad = client.post(f"/api/tasks/{task_id}/reading-position", json={"page": 0})
        still_none = client.get(f"/api/tasks/{task_id}").json()["last_read_page"]

    assert bad.status_code == 422
    assert still_none is None


def test_reading_position_missing_task_404() -> None:
    with TestClient(app) as client:
        res = client.post("/api/tasks/9999/reading-position", json={"page": 1})

    assert res.status_code == 404
