"""N42 概览 + N43 检查历史列表的用例。

盯四件事：
1. ⭐ **概览全是真计数**（建几条就是几条），`tasks`/`blocks` **不含归档**、归档单独给；
2. ⭐ **检查历史只列自己的**（别人的一条都别出现）；
3. ⭐ 列表按新→旧、`draft_id` 能筛、`limit` 有上限；
4. ⭐ 列表带的是**摘要**（reported/unknown），不是整份报告。

⚠️ 不用 `tmp_path`（AGENTS.md：受限环境不可写）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import TEST_USER_ID, create_user_row
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import (
    CheckRun,
    Citation,
    Draft,
    Material,
    Task,
    TaskBlock,
    User,
)
from app.timeutil import utc_now

client = TestClient(app)


def _task(filename: str, **kwargs) -> int:
    with SessionLocal() as session:
        row = Task(
            user_id=kwargs.pop("user_id", TEST_USER_ID),
            filename=filename,
            tier="fast",
            status="completed",
            progress=1.0,
            source_lang="en",
            target_lang="zh",
            **kwargs,
        )
        session.add(row)
        session.flush()
        task_id = row.id
        session.commit()
        return task_id


def _block(task_id: int, block_id: str) -> None:
    with SessionLocal() as session:
        session.add(
            TaskBlock(
                task_id=task_id,
                block_id=block_id,
                text="hello",
                translated="你好",
                status="success",
            )
        )
        session.commit()


def _draft(title: str, user_id: int = TEST_USER_ID) -> int:
    with SessionLocal() as session:
        row = Draft(user_id=user_id, title=title, body_md="正文")
        session.add(row)
        session.commit()
        return row.id


def _citation(draft_id: int, order: int, material_id: int) -> None:
    """引文必须挂在素材上（`material_id` NOT NULL），所以先把素材 id 传进来。"""
    with SessionLocal() as session:
        session.add(
            Citation(
                draft_id=draft_id,
                material_id=material_id,
                order=order,
                anchor=f"[{order}]",
                csl_json={"id": f"c{order}", "type": "article-journal"},
            )
        )
        session.commit()


def _material(user_id: int = TEST_USER_ID) -> int:
    with SessionLocal() as session:
        row = Material(
            user_id=user_id,
            task_id=_task("m.pdf", user_id=user_id),
            block_id="b0",
            text_quote="引文",
            page=1,
            note="",
            source_name="m.pdf",
        )
        session.add(row)
        session.flush()  # 先拿 id：commit 会 expire 对象，refresh 反而不稳
        material_id = row.id
        session.commit()
        return material_id


def _check_run(
    draft_id: int | None,
    user_id: int = TEST_USER_ID,
    reported: int = 2,
    unknown: int = 0,
) -> int:
    with SessionLocal() as session:
        row = CheckRun(
            user_id=user_id,
            draft_id=draft_id,
            lang="zh",
            citation_style="numeric",
            ruleset_version=2,
            report={
                "summary": {"reported": reported, "unknown": unknown},
                "step": {"lang": "zh", "citation_style": "numeric"},
                "findings": [],
            },
        )
        session.add(row)
        session.commit()
        return row.id


def test_overview_counts_are_real() -> None:
    """⭐ 建多少就是多少（不编、不估）。"""
    draft_id = _draft("稿子")
    material_id = _material()
    _citation(draft_id, 1, material_id)
    _citation(draft_id, 2, material_id)
    task_id = _task("a.pdf")
    _block(task_id, "p0_b0")
    _block(task_id, "p0_b1")
    _check_run(draft_id)

    res = client.get("/api/me/overview")
    assert res.status_code == 200
    data = res.json()
    assert data["tasks"] >= 1
    assert data["blocks"] >= 2
    assert data["materials"] >= 1
    assert data["drafts"] >= 1
    assert data["citations"] >= 2
    assert data["check_runs"] >= 1


def test_overview_excludes_archived_tasks_and_blocks() -> None:
    """⭐ 归档的文献不算在 tasks/blocks 里（与列表同一口径），但单独给一个数。"""
    before = client.get("/api/me/overview").json()

    archived = _task("archived.pdf", archived_at=utc_now())
    _block(archived, "p0_b0")

    after = client.get("/api/me/overview").json()
    assert after["tasks"] == before["tasks"], "归档的文献不该算进 tasks"
    assert after["blocks"] == before["blocks"], "归档文献的块不该算进 blocks"
    assert after["archived_tasks"] == before["archived_tasks"] + 1


def test_check_history_lists_only_mine() -> None:
    """⭐ 别人的检查记录一条都不许出现。"""
    create_user_row("other_hist", "pw-for-test")
    with SessionLocal() as session:
        other_id = session.scalar(select(User.id).where(User.username == "other_hist"))

    mine = _check_run(None)
    theirs = _check_run(None, user_id=other_id)

    ids = [item["id"] for item in client.get("/api/check").json()["items"]]
    assert mine in ids
    assert theirs not in ids


def test_check_history_newest_first_and_summary_only() -> None:
    """⭐ 新→旧；每条只带摘要，不塞整份报告。"""
    first = _check_run(None, reported=1)
    second = _check_run(None, reported=3, unknown=1)

    items = client.get("/api/check").json()["items"]
    ids = [item["id"] for item in items]
    assert ids.index(second) < ids.index(first)

    item = next(row for row in items if row["id"] == second)
    assert item["summary"] == {"reported": 3, "unknown": 1}
    assert "findings" not in item, "列表里不该有逐条明细（走 N23 点开看）"
    assert item["created_at"].endswith("+00:00")


def test_check_history_can_filter_by_draft() -> None:
    draft_a = _draft("A 稿")
    draft_b = _draft("B 稿")
    run_a = _check_run(draft_a)
    run_b = _check_run(draft_b)

    ids = [
        item["id"]
        for item in client.get(f"/api/check?draft_id={draft_a}").json()["items"]
    ]
    assert run_a in ids
    assert run_b not in ids


def test_check_history_limit_is_capped() -> None:
    """`limit` 有上限（50），避免一次把历史全拖回来。"""
    for _ in range(3):
        _check_run(None)
    items = client.get("/api/check?limit=9999").json()["items"]
    assert len(items) <= 50
