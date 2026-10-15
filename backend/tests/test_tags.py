"""知识库 · 标签（契约 §2.2 / N6–N7）的测试。

盯四件事：

1. **按名字 upsert**：同一个 `(name, kind)` 反复给只留一行、`id` 稳定；
2. ⭐ **`kind='status'` 的标签与 `tasks.reading_status` 互不影响**——改一个另一个必须不动
   （契约与数据模型都把这条写死了：前者是用户自己额外打的标签，后者驱动那三个入口）；
3. **N7 是全量替换**（PUT 语义）：第二次只给一个标签，旧的就得下来；
4. **归属**：别人的文献 404。

⚠️ 不用 `tmp_path`（AGENTS.md：受限环境不可写）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import TEST_USER_ID, create_user_row

from app.db import SessionLocal
from app.main import app
from app.models import Tag, Task, TaskTag

client = TestClient(app)


def _task(*, user_id: int = TEST_USER_ID, reading_status: str = "todo") -> int:
    with SessionLocal() as session:
        row = Task(
            user_id=user_id,
            filename="p.pdf",
            status="completed",
            reading_status=reading_status,
        )
        session.add(row)
        session.commit()
        return row.id


def _items(kind: str | None = None) -> dict[str, dict]:
    url = "/api/tags" if kind is None else f"/api/tags?kind={kind}"
    response = client.get(url)
    assert response.status_code == 200
    return {row["name"]: row for row in response.json()["items"]}


def test_n7_upserts_by_name_and_reports_counts():
    task_id = _task()
    response = client.put(
        f"/api/tasks/{task_id}/tags",
        json={
            "tags": [
                {"name": "RAG", "kind": "topic"},
                {"name": "双盲", "kind": "method"},
            ]
        },
    )
    assert response.status_code == 200
    saved = response.json()["tags"]
    assert {row["name"] for row in saved} == {"RAG", "双盲"}
    rag_id = next(row["id"] for row in saved if row["name"] == "RAG")

    # 同一 (name, kind) 再来一次：还是那一行（upsert，不是插新的）
    response = client.put(
        f"/api/tasks/{task_id}/tags", json={"tags": [{"name": "RAG", "kind": "topic"}]}
    )
    assert response.json()["tags"][0]["id"] == rag_id
    with SessionLocal() as session:
        rows = session.query(Tag).filter_by(user_id=TEST_USER_ID, name="RAG")
        assert rows.count() == 1

    items = _items()
    assert items["RAG"]["doc_count"] == 1
    assert items["RAG"]["kind"] == "topic"
    # 上一次的「双盲」被全量替换掉：标签表里还在（可能别的文献在用），但这篇不再挂它
    with SessionLocal() as session:
        assert session.query(TaskTag).filter_by(task_id=task_id).count() == 1


def test_invalid_kind_or_empty_name_is_400():
    task_id = _task()
    for payload in (
        {"tags": [{"name": "x", "kind": "wrong"}]},
        {"tags": [{"name": "   ", "kind": "topic"}]},
        {"tags": [{"name": "x"}]},
    ):
        response = client.put(f"/api/tasks/{task_id}/tags", json=payload)
        assert response.status_code in (400, 422), payload


def test_status_tag_and_reading_status_do_not_sync():
    """⭐ 两张东西互不影响：打 `status` 标签不动 `reading_status`，反之亦然。"""
    task_id = _task(reading_status="todo")
    client.put(
        f"/api/tasks/{task_id}/tags",
        json={"tags": [{"name": "已读", "kind": "status"}]},
    )
    with SessionLocal() as session:
        assert session.get(Task, task_id).reading_status == "todo"

    # 反过来：改 reading_status（走任务表），标签一枚不少
    with SessionLocal() as session:
        row = session.get(Task, task_id)
        row.reading_status = "done"
        session.commit()
    with SessionLocal() as session:
        assert session.query(TaskTag).filter_by(task_id=task_id).count() == 1
    assert _items("status")["已读"]["name"] == "已读"


def test_kind_filter_and_unknown_kind_is_empty():
    task_id = _task()
    client.put(
        f"/api/tasks/{task_id}/tags",
        json={
            "tags": [
                {"name": "RAG", "kind": "topic"},
                {"name": "方法甲", "kind": "method"},
            ]
        },
    )
    assert set(_items("topic")) == {"RAG"}
    assert set(_items("method")) == {"方法甲"}
    # 认不出的 kind 回空表（与前端 mock 一致，不是错误）
    assert client.get("/api/tags?kind=nope").json() == {"items": []}


def test_others_task_is_404():
    other = create_user_row("other-tags", "pw-other")
    their_task = _task(user_id=other)
    response = client.put(
        f"/api/tasks/{their_task}/tags", json={"tags": [{"name": "x", "kind": "topic"}]}
    )
    assert response.status_code == 404
    assert client.get("/api/tags").json()["items"] == []
