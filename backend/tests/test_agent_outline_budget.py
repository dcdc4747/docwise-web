"""`read_section` 接读段预算（`app/agent/read_budget.py`）的用例。

盯五件事：

1. 第一次读照常成功，预算记 1 次，key 是 `sec:{task_id}:{index}`，
   记录的字数就是**真给出去的**字数（截断时记 6000，不是全节长度）；
2. 同一节第二次读被拒：`data=[]`，note 说明"读过"；
3. 不同 index、不同文献互不影响；
4. 被拒时**一块内容都不取**（只查一次归属；省时间也省钱），也不再多记一次；
5. `list_sections` 完全不受影响（它不占读段预算）。

⚠️ 预算按 (用户, 工具, 文献) 在**进程内**缓存，用例之间必须 `reset_all()`。
`_clean_budget` 在每个用例前后都清一遍——既让本文件的用例互不干扰，
也避免缓存漏到后面跑的 `test_agent_pack_outline.py`。
⚠️ 不用 `tmp_path`（受限环境不可写）：数据自己建、自己清。
"""

from __future__ import annotations

import pytest
from helpers import TEST_USER_ID

from app.agent.contracts import ToolContext
from app.agent.packs import outline
from app.agent.packs._budget import budget_for, reset_all
from app.agent.read_budget import ReadBudget
from app.db import SessionLocal
from app.models import Task, TaskBlock

# 一篇小样本：题名 + Abstract + 两节，正文夹在标题之间（与 outline 既有用例同形）。
# 章节（`list_sections` 的 index）：0 题名 / 1 Abstract / 2 引言 / 3 方法
_SAMPLE = [
    (
        "p0_b0",
        "Chiral Time Structure in Molecular Rotation Dynamics",
        "分子旋转动力学中的手性时间结构",
    ),
    ("p0_b1", "Abstract", "摘要"),
    ("p0_b2", "We study the chiral structure of rotational wavepackets.", None),
    ("p0_b3", "1. Introduction", "一、引言"),
    ("p0_b4", "Chirality plays a central role.", None),
    ("p0_b5", "2. Methods", "二、方法"),
    ("p0_b6", "We measured the orientation trajectories.", "我们测量了取向轨迹。"),
]

_REPEAT_NOTE = "这一节已经读过了，用前面的内容回答；确实需要重读请说明原因。"


@pytest.fixture(autouse=True)
def _clean_budget():
    """进程内预算缓存：每个用例前后都清干净（否则 task_id 复用会串味）。"""
    reset_all()
    yield
    reset_all()


def _ctx(user_id: int = TEST_USER_ID) -> ToolContext:
    """scope 留空：预算只按 (用户, 工具) 缓存，key 里的 task_id 才真的要起作用。"""
    return ToolContext(db=None, user_id=user_id, scene_id="read_ask", scope={})


def _budget(ctx: ToolContext) -> ReadBudget:
    """取 read_section 正在用的那个预算对象（同一个缓存实例）。"""
    return budget_for(ctx, "read_section")


def _make_task(
    blocks: list[tuple[str, str, str | None]],
    *,
    user_id: int = TEST_USER_ID,
) -> int:
    """直接入库建一篇文献与它的块，返回 task_id。"""
    with SessionLocal() as session:
        task = Task(user_id=user_id, filename="outline.pdf", status="completed")
        session.add(task)
        session.flush()
        for block_id, text, translated in blocks:
            session.add(
                TaskBlock(
                    task_id=task.id,
                    block_id=block_id,
                    text=text,
                    translated=translated,
                )
            )
        session.commit()
        return task.id


def _cleanup(task_id: int) -> None:
    with SessionLocal() as session:
        session.query(TaskBlock).filter_by(task_id=task_id).delete()
        task = session.get(Task, task_id)
        if task is not None:
            session.delete(task)
        session.commit()


# ============================================================ ① 第一次读


def test_first_read_succeeds_and_records_one_read() -> None:
    task_id = _make_task(_SAMPLE)
    try:
        ctx = _ctx()
        got = outline.read_section(ctx, {"task_id": task_id, "index": 2})

        # 返回结构没动：块列表 / truncated / 其它字段都还在
        assert set(got.data) == {
            "task_id",
            "index",
            "kind",
            "title",
            "blocks",
            "truncated",
        }
        assert got.data["title"] == "一、引言"
        assert got.data["truncated"] is False
        assert [b["block_id"] for b in got.data["blocks"]] == ["p0_b3", "p0_b4"]

        stats = _budget(ctx).stats()
        assert stats["reads"] == 1
        assert stats["keys"] == [f"sec:{task_id}:2"]
        # 记的是真给出去的字数（含标题块那几字）
        assert stats["chars"] == sum(
            len(block["text"]) for block in got.data["blocks"]
        )
    finally:
        _cleanup(task_id)


def test_truncated_read_records_returned_chars_only() -> None:
    """截断时按 6000 记，不是按整节长度记。"""
    task_id = _make_task(
        [
            ("p1_b0", "一、超长一节", None),
            ("p1_b1", "original paragraph", "长" * 7000),
        ]
    )
    try:
        ctx = _ctx()
        got = outline.read_section(ctx, {"task_id": task_id, "index": 0})
        assert got.data["truncated"] is True
        assert "6000" in got.note
        stats = _budget(ctx).stats()
        assert stats["reads"] == 1
        assert stats["chars"] == 6000
    finally:
        _cleanup(task_id)


# ============================================================ ② 重读被拒


def test_second_read_of_same_section_is_rejected() -> None:
    task_id = _make_task(_SAMPLE)
    try:
        ctx = _ctx()
        first = outline.read_section(ctx, {"task_id": task_id, "index": 2})
        assert first.data["blocks"], "第一次要正常读到内容"

        again = outline.read_section(ctx, {"task_id": task_id, "index": 2})
        assert again.data == []
        assert again.note == _REPEAT_NOTE
        assert "读过" in again.note

        # 被拒不多记一次
        stats = _budget(ctx).stats()
        assert stats["reads"] == 1
        assert stats["keys"] == [f"sec:{task_id}:2"]
    finally:
        _cleanup(task_id)


def test_denied_read_does_not_load_blocks(monkeypatch) -> None:
    """被拒的那一次**一块内容都不取**（`_load_blocks` 不该被调到）。"""
    task_id = _make_task(_SAMPLE)
    try:
        ctx = _ctx()
        outline.read_section(ctx, {"task_id": task_id, "index": 2})

        looked_up: list[int] = []

        def _boom(db, tid):
            looked_up.append(tid)
            raise AssertionError("被拒的读不许再取块")

        monkeypatch.setattr(outline, "_load_blocks", _boom)
        denied = outline.read_section(ctx, {"task_id": task_id, "index": 2})
        assert denied.data == []
        assert denied.note == _REPEAT_NOTE
        assert looked_up == []
        assert _budget(ctx).stats()["reads"] == 1
    finally:
        _cleanup(task_id)


# ============================================================ ③ 互不影响


def test_different_index_is_not_blocked() -> None:
    task_id = _make_task(_SAMPLE)
    try:
        ctx = _ctx()
        intro = outline.read_section(ctx, {"task_id": task_id, "index": 2})
        methods = outline.read_section(ctx, {"task_id": task_id, "index": 3})

        assert intro.data["title"] == "一、引言"
        assert methods.data["title"] == "二、方法"
        assert [b["block_id"] for b in methods.data["blocks"]] == [
            "p0_b5",
            "p0_b6",
        ]

        stats = _budget(ctx).stats()
        assert stats["reads"] == 2
        assert stats["keys"] == [f"sec:{task_id}:2", f"sec:{task_id}:3"]
    finally:
        _cleanup(task_id)


def test_same_index_in_another_document_is_not_blocked() -> None:
    """key 里带 task_id：另一篇的第 2 节没读过，照样能读。"""
    first_id = _make_task(_SAMPLE)
    second_id = _make_task(_SAMPLE)
    try:
        ctx = _ctx()
        outline.read_section(ctx, {"task_id": first_id, "index": 2})
        other = outline.read_section(ctx, {"task_id": second_id, "index": 2})

        assert other.data["title"] == "一、引言"
        assert _budget(ctx).stats()["keys"] == [
            f"sec:{first_id}:2",
            f"sec:{second_id}:2",
        ]
    finally:
        _cleanup(first_id)
        _cleanup(second_id)


# ============================================================ ④ 不碰列结构


def test_list_sections_is_unaffected_by_the_budget() -> None:
    task_id = _make_task(_SAMPLE)
    try:
        ctx = _ctx()
        before = outline.list_sections(ctx, {"task_id": task_id})
        outline.read_section(ctx, {"task_id": task_id, "index": 2})
        denied = outline.read_section(ctx, {"task_id": task_id, "index": 2})
        after = outline.list_sections(ctx, {"task_id": task_id})

        assert denied.data == []
        assert after.data == before.data
        assert after.note == before.note
        # 列结构不占读段预算
        assert _budget(ctx).stats()["reads"] == 1
    finally:
        _cleanup(task_id)
