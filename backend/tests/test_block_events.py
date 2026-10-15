"""埋点 1（契约 §2.9–§2.10 / N33–N34）的测试。

盯四件事：

1. ⭐ **人工改动留痕是真的**：`before` / `after` / 原文哈希都落库，
   并且该块的译文**变成用户那一版**（不改的话界面刷新就回去了）；
2. ⭐ **归属与存在性**：别人的任务 404、块不在本任务 404（不暴露"存在但无权限"）；
3. ⭐ **曝光幂等**：同一 `(user, task, block, session)` 重复上报**不长新行**，
   只把 `left_at` 往后推（契约 §2.10 的唯一约束就是判据）；
4. ⭐ **两者都进台账**：改动写一条 `stage="edit"`；曝光**一次会话只写一条**
   （不是每块一条——否则一次精读 80 块就把台账淹了）。

⚠️ 不用 `tmp_path`（AGENTS.md：受限环境不可写）。
"""

from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient
from helpers import TEST_USER_ID, create_user_row
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import BlockEdit, BlockExposure, MemoryEvent, Task, TaskBlock


def _make_task(*, user_id: int = TEST_USER_ID, filename: str = "math.pdf") -> int:
    with SessionLocal() as session:
        row = Task(user_id=user_id, filename=filename, status="completed")
        session.add(row)
        session.commit()
        return row.id


def _make_block(
    *,
    task_id: int,
    block_id: str = "p0_b1",
    text: str = "原文一句话",
    translated: str | None = "模型译文",
) -> None:
    with SessionLocal() as session:
        session.add(
            TaskBlock(
                task_id=task_id,
                block_id=block_id,
                text=text,
                translated=translated,
            )
        )
        session.commit()


def _edits() -> list[BlockEdit]:
    with SessionLocal() as session:
        rows = list(session.scalars(select(BlockEdit).order_by(BlockEdit.id)).all())
        for row in rows:
            session.expunge(row)
        return rows


def _exposures() -> list[BlockExposure]:
    with SessionLocal() as session:
        rows = list(
            session.scalars(select(BlockExposure).order_by(BlockExposure.id)).all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def _events(*, stage: str) -> list[MemoryEvent]:
    stmt = (
        select(MemoryEvent)
        .where(MemoryEvent.stage == stage)
        .order_by(MemoryEvent.id)
    )
    with SessionLocal() as session:
        rows = list(session.scalars(stmt).all())
        for row in rows:
            session.expunge(row)
        return rows


def _translated(task_id: int, block_id: str) -> str | None:
    with SessionLocal() as session:
        row = session.scalars(
            select(TaskBlock).where(
                TaskBlock.task_id == task_id, TaskBlock.block_id == block_id
            )
        ).first()
        return row.translated if row else None


# ============================================================ N33 译文改动


def test_edit_records_before_after_hash_and_updates_block() -> None:
    task_id = _make_task()
    _make_block(task_id=task_id, block_id="p2_b7", text="原始英文句子")

    with TestClient(app) as client:
        resp = client.post(
            "/api/block-edits",
            json={
                "task_id": task_id,
                "block_id": "p2_b7",
                "before": "模型译文",
                "after": "人工润色后的译文",
            },
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["edited"] is True

    rows = _edits()
    assert len(rows) == 1
    assert rows[0].before == "模型译文"
    assert rows[0].after == "人工润色后的译文"
    # 原文哈希由服务端算：改的是哪一句有据可查
    assert rows[0].text_hash == hashlib.sha256("原始英文句子".encode()).hexdigest()
    # ⭐ 该块的译文变成用户那一版（否则刷新就回去了）
    assert _translated(task_id, "p2_b7") == "人工润色后的译文"


def test_edit_writes_ledger_event_with_diff() -> None:
    task_id = _make_task()
    _make_block(task_id=task_id, block_id="p0_b1")

    with TestClient(app) as client:
        client.post(
            "/api/block-edits",
            json={
                "task_id": task_id,
                "block_id": "p0_b1",
                "before": "旧译文",
                "after": "新译文",
            },
        )
    events = _events(stage="edit")
    assert len(events) == 1
    assert events[0].actor == "user"
    payload = events[0].payload or {}
    # 台账里要能逐条看 diff —— 改前改后都带上
    assert payload.get("before") == "旧译文"
    assert payload.get("after") == "新译文"
    assert payload.get("block_id") == "p0_b1"


def test_edit_rejects_unchanged_and_blank_400() -> None:
    task_id = _make_task()
    _make_block(task_id=task_id, block_id="p0_b1")

    with TestClient(app) as client:
        same = client.post(
            "/api/block-edits",
            json={
                "task_id": task_id,
                "block_id": "p0_b1",
                "before": "一模一样",
                "after": "一模一样",
            },
        )
        blank = client.post(
            "/api/block-edits",
            json={
                "task_id": task_id,
                "block_id": "p0_b1",
                "before": "旧",
                "after": "   ",
            },
        )
    assert same.status_code == 400, same.text
    assert blank.status_code == 400, blank.text
    # 两次都不该留痕
    assert _edits() == []


def test_edit_rejects_foreign_task_and_unknown_block() -> None:
    other_user = create_user_row("someone-else", "pw123456")
    foreign_task = _make_task(user_id=other_user, filename="other.pdf")
    _make_block(task_id=foreign_task, block_id="p0_b1")
    mine = _make_task()
    _make_block(task_id=mine, block_id="p0_b1")

    with TestClient(app) as client:
        foreign = client.post(
            "/api/block-edits",
            json={
                "task_id": foreign_task,
                "block_id": "p0_b1",
                "before": "a",
                "after": "b",
            },
        )
        unknown = client.post(
            "/api/block-edits",
            json={
                "task_id": mine,
                "block_id": "p9_b9",
                "before": "a",
                "after": "b",
            },
        )
    # 别人的任务：404（不暴露"存在但无权限"）
    assert foreign.status_code == 404, foreign.text
    # 块不在本任务：404
    assert unknown.status_code == 404, unknown.text
    assert _edits() == []


def test_list_edits_returns_newest_first_and_only_mine() -> None:
    mine = _make_task()
    _make_block(task_id=mine, block_id="p0_b1")
    other_user = create_user_row("another", "pw123456")
    theirs = _make_task(user_id=other_user, filename="theirs.pdf")
    _make_block(task_id=theirs, block_id="p0_b1")

    with TestClient(app) as client:
        client.post(
            "/api/block-edits",
            json={"task_id": mine, "block_id": "p0_b1", "before": "v1", "after": "v2"},
        )
        client.post(
            "/api/block-edits",
            json={"task_id": mine, "block_id": "p0_b1", "before": "v2", "after": "v3"},
        )
        # 直接往别人的号里塞一条（绕过接口，证明读取按账号过滤）
        with SessionLocal() as session:
            session.add(
                BlockEdit(
                    user_id=other_user,
                    task_id=theirs,
                    block_id="p0_b1",
                    text_hash="x" * 64,
                    before="他们的",
                    after="他们的新",
                )
            )
            session.commit()
        resp = client.get("/api/block-edits", params={"task_id": mine})

    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert [item["after"] for item in items] == ["v3", "v2"]
    assert all(item["task_id"] == mine for item in items)


# ============================================================ N34 曝光


def test_exposure_is_idempotent_per_session() -> None:
    task_id = _make_task()
    _make_block(task_id=task_id, block_id="p0_b1")

    body = {
        "task_id": task_id,
        "block_id": "p0_b1",
        "session_id": "sess-1",
        "entered_at": "2026-10-16T01:00:00+00:00",
        "left_at": "2026-10-16T01:00:02+00:00",
    }
    with TestClient(app) as client:
        first = client.post("/api/block-exposures", json=body)
        second = client.post(
            "/api/block-exposures",
            json={**body, "left_at": "2026-10-16T01:00:09+00:00"},
        )
    assert first.status_code == 201, first.text
    assert first.json()["created"] is True
    assert second.status_code == 201, second.text
    assert second.json()["created"] is False
    # ⭐ 幂等：重复上报**不长新行**
    rows = _exposures()
    assert len(rows) == 1
    # 但"看了更久"要记上
    assert rows[0].left_at > rows[0].entered_at


def test_exposure_different_session_is_a_new_row() -> None:
    task_id = _make_task()
    _make_block(task_id=task_id, block_id="p0_b1")

    with TestClient(app) as client:
        for session_id in ("s1", "s2"):
            client.post(
                "/api/block-exposures",
                json={
                    "task_id": task_id,
                    "block_id": "p0_b1",
                    "session_id": session_id,
                },
            )
    assert len(_exposures()) == 2


def test_exposure_writes_one_ledger_event_per_session() -> None:
    task_id = _make_task()
    _make_block(task_id=task_id, block_id="p0_b1")
    _make_block(task_id=task_id, block_id="p0_b2")

    with TestClient(app) as client:
        for block_id in ("p0_b1", "p0_b2"):
            client.post(
                "/api/block-exposures",
                json={"task_id": task_id, "block_id": block_id, "session_id": "s1"},
            )
    # ⭐ 一次会话一条，不是每块一条
    events = _events(stage="exposure")
    assert len(events) == 1
    assert (events[0].payload or {}).get("session_id") == "s1"
    # 曝光是本地行为（没有内容出本机）
    assert events[0].actor == "local"


def test_exposure_rejects_foreign_task_404() -> None:
    other_user = create_user_row("stranger", "pw123456")
    foreign_task = _make_task(user_id=other_user, filename="foreign.pdf")
    _make_block(task_id=foreign_task, block_id="p0_b1")

    with TestClient(app) as client:
        resp = client.post(
            "/api/block-exposures",
            json={
                "task_id": foreign_task,
                "block_id": "p0_b1",
                "session_id": "s1",
            },
        )
    assert resp.status_code == 404, resp.text
    assert _exposures() == []
