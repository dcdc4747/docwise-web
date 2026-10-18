"""素材工具包（`app/agent/packs/materials.py`）的用例。

盯四件事：

1. 能列我的素材卡、能按关键词过滤，**源文献已删的卡要标出来**；
2. 别人的素材读不到（越权不能靠前端拦）；
3. 写工具不带 `confirm` 时**一行都不许写**（建卡是用户的动作）；
4. 带 `confirm=true` 且块存在时，快照字段与页码都要对。

⚠️ 不用 `tmp_path`（AGENTS.md：受限环境不可写）；数据自己建、自己清。
"""

from __future__ import annotations

from helpers import TEST_USER_ID

from app.agent.contracts import ToolContext
from app.agent.packs import materials as materials_pack
from app.db import SessionLocal
from app.models import Material, Task, TaskBlock
from app.timeutil import utc_now


def _ctx() -> ToolContext:
    return ToolContext(
        db=None,
        user_id=TEST_USER_ID,
        scene_id="write_compose",
        scope={},
    )


def _make_task(
    *, user_id: int = TEST_USER_ID, filename: str = "chem_arXiv.pdf"
) -> int:
    with SessionLocal() as session:
        row = Task(user_id=user_id, filename=filename, status="completed")
        session.add(row)
        session.commit()
        return row.id


def _make_block(
    *,
    task_id: int,
    block_id: str = "p0_b1",
    text: str = "the chiral measures are conserved",
    translated: str | None = "手性测度是守恒的",
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


def _count() -> int:
    with SessionLocal() as session:
        return session.query(Material).count()


def _drop(*, task_ids=(), material_ids=()) -> None:
    with SessionLocal() as session:
        for material_id in material_ids:
            row = session.get(Material, material_id)
            if row is not None:
                session.delete(row)
        for task_id in task_ids:
            session.query(TaskBlock).filter_by(task_id=task_id).delete()
            task = session.get(Task, task_id)
            if task is not None:
                session.delete(task)
        session.commit()


# ============================================================ ① 列素材


def test_list_materials_filters_by_keyword_and_flags_deleted_source() -> None:
    task_id = _make_task(filename="chem_arXiv.pdf")
    with SessionLocal() as session:
        hit = Material(
            user_id=TEST_USER_ID,
            task_id=task_id,
            block_id="p2_b7",
            text_quote="the chiral measures are conserved",
            translated_quote="手性测度是守恒的",
            page=3,
            source_name="chem_arXiv.pdf",
        )
        miss = Material(
            user_id=TEST_USER_ID,
            task_id=task_id,
            text_quote="sparse linear systems",
            translated_quote="稀疏线性系统",
            page=7,
            source_name="math_arXiv.pdf",
        )
        orphan = Material(
            user_id=TEST_USER_ID,
            task_id=None,
            text_quote="手性时间结构可以分成两部分",
            translated_quote=None,
            page=5,
            source_name="deleted.pdf",
        )
        gone = Material(
            user_id=TEST_USER_ID,
            text_quote="这条已经软删了",
            page=1,
            source_name="gone.pdf",
            deleted_at=utc_now(),
        )
        session.add_all([hit, miss, orphan, gone])
        session.commit()
        hit_id, miss_id, orphan_id, gone_id = (
            hit.id,
            miss.id,
            orphan.id,
            gone.id,
        )

    ctx = _ctx()
    everything = materials_pack.list_materials(ctx, {"limit": 10})
    ids = {item["material_id"] for item in everything.data}
    assert ids == {hit_id, miss_id, orphan_id}
    assert gone_id not in ids, "软删的卡不该出现在列表里"

    flagged = [item for item in everything.data if item["source_deleted"]]
    assert [item["material_id"] for item in flagged] == [orphan_id]
    assert "源文献已删除" in everything.note

    filtered = materials_pack.list_materials(ctx, {"query": "手性"})
    filtered_ids = {item["material_id"] for item in filtered.data}
    assert filtered_ids == {hit_id, orphan_id}
    card = next(item for item in filtered.data if item["material_id"] == hit_id)
    assert card["quote"] == "the chiral measures are conserved"
    assert card["source"] == "chem_arXiv.pdf"
    assert card["page"] == 3

    _drop(
        task_ids=[task_id],
        material_ids=[hit_id, miss_id, orphan_id, gone_id],
    )


# ============================================================ ② 读一条 / 越权


def test_get_material_returns_snapshot_and_hides_others() -> None:
    task_id = _make_task(filename="chem_arXiv.pdf")
    mine = Material(
        user_id=TEST_USER_ID,
        task_id=task_id,
        text_quote="the chiral measures are conserved",
        translated_quote="手性测度是守恒的",
        page=3,
        source_name="chem_arXiv.pdf",
        note="可当引文",
    )
    theirs = Material(
        user_id=TEST_USER_ID + 999,
        text_quote="别人的原文",
        translated_quote=None,
        page=1,
        source_name="theirs.pdf",
    )
    with SessionLocal() as session:
        session.add_all([mine, theirs])
        session.commit()
        mine_id, theirs_id = mine.id, theirs.id

    ctx = _ctx()
    got = materials_pack.get_material(ctx, {"material_id": mine_id})
    assert got.data["text_quote"] == "the chiral measures are conserved"
    assert got.data["translated_quote"] == "手性测度是守恒的"
    assert got.data["source_name"] == "chem_arXiv.pdf"
    assert got.data["page"] == 3
    assert got.data["note"] == "可当引文"
    assert got.data["source_deleted"] is False

    denied = materials_pack.get_material(ctx, {"material_id": theirs_id})
    assert "找不到" in str(denied.data)
    assert not isinstance(denied.data, dict)

    _drop(task_ids=[task_id], material_ids=[mine_id, theirs_id])


# ============================================================ ③ 不带 confirm


def test_create_without_confirm_writes_nothing() -> None:
    task_id = _make_task()
    _make_block(task_id=task_id, block_id="p1_b3")
    before = _count()

    ctx = _ctx()
    for args in (
        {"task_id": task_id, "block_id": "p1_b3"},
        {"task_id": task_id, "block_id": "p1_b3", "confirm": False},
        {"task_id": task_id, "block_id": "p1_b3", "confirm": "true"},
    ):
        result = materials_pack.create_material(ctx, args)
        assert result.data["status"] == "needs_confirmation"
        assert "确认" in result.note

    assert _count() == before, "没确认就不许写库"
    _drop(task_ids=[task_id])


# ============================================================ ④ 带 confirm


def test_create_with_confirm_writes_snapshot() -> None:
    task_id = _make_task(filename="chem_arXiv_2609.37896v1.pdf")
    _make_block(
        task_id=task_id,
        block_id="p1_b3",
        text="the chiral measures are conserved",
        translated="手性测度是守恒的",
    )
    before = _count()

    result = materials_pack.create_material(
        _ctx(),
        {"task_id": task_id, "block_id": "p1_b3", "confirm": True},
    )
    assert _count() == before + 1
    material_id = result.data["material_id"]

    with SessionLocal() as session:
        row = session.get(Material, material_id)
    assert row is not None
    assert row.user_id == TEST_USER_ID
    assert row.task_id == task_id
    assert row.block_id == "p1_b3"
    assert row.text_quote == "the chiral measures are conserved"
    assert row.translated_quote == "手性测度是守恒的"
    assert row.source_name == "chem_arXiv_2609.37896v1.pdf"
    assert row.page == 2, "p1 → 人读第 2 页"

    _drop(task_ids=[task_id], material_ids=[material_id])


# ============================================================ ⑤ 归属 / 页


def test_create_refuses_other_users_task() -> None:
    task_id = _make_task(user_id=TEST_USER_ID + 999, filename="theirs.pdf")
    _make_block(task_id=task_id, block_id="p0_b1")
    before = _count()

    result = materials_pack.create_material(
        _ctx(),
        {"task_id": task_id, "block_id": "p0_b1", "confirm": True},
    )
    assert "找不到" in str(result.data)
    assert _count() == before, "别人的文献不许写成我的素材"

    _drop(task_ids=[task_id])


def test_create_without_derivable_page_writes_nothing() -> None:
    task_id = _make_task()
    _make_block(task_id=task_id, block_id="scan-block-7")
    before = _count()

    result = materials_pack.create_material(
        _ctx(),
        {"task_id": task_id, "block_id": "scan-block-7", "confirm": True},
    )
    assert "页码" in result.note
    assert _count() == before, "推不出页码就不建卡（不编页码）"

    _drop(task_ids=[task_id])
