"""翻译工具包（translate）的五条底线。

1. 能读到自己的进度（状态 / 百分比 / 阶段 / 语言对 / 档位 / 块数）；
2. 别人的任务一律当作「找不到」；
3. `request_retranslate` 不带 `confirm` 时**一个字都不改**（断言 status 没变）；
4. 用户真确认了才置回待处理；
5. `args` 是 None / 不是 dict 时也不炸（runtime 传什么进来都得接住）。
"""

from __future__ import annotations

from helpers import TEST_USER_ID

from app.agent.contracts import ToolContext
from app.agent.packs import translate as translate_pack
from app.db import SessionLocal
from app.models import Task, TaskBlock


def _ctx(user_id: int = TEST_USER_ID) -> ToolContext:
    return ToolContext(db=None, user_id=user_id, scene_id="read_ask", scope={})


def _make_task(**fields) -> int:
    with SessionLocal() as session:
        task = Task(user_id=TEST_USER_ID, filename="chem_arXiv.pdf", **fields)
        session.add(task)
        session.commit()
        return task.id


def _status_of(task_id: int) -> str:
    """从库里重读状态（不信任工具返回值，直接看落库结果）。"""
    with SessionLocal() as session:
        task = session.get(Task, task_id)
        assert task is not None
        return str(task.status)


def _cleanup(*task_ids: int) -> None:
    with SessionLocal() as session:
        for task_id in task_ids:
            session.query(TaskBlock).filter_by(task_id=task_id).delete()
            task = session.get(Task, task_id)
            if task is not None:
                session.delete(task)
        session.commit()


def test_get_progress_reads_my_task() -> None:
    """① 自己造一个任务，进度、阶段、块数都读得回来。"""
    task_id = _make_task(
        status="in_progress",
        progress=0.42,
        stage="translating",
        eta_seconds=90,
        source_lang="en",
        target_lang="zh",
        tier="medium",
    )
    with SessionLocal() as session:
        session.add(TaskBlock(task_id=task_id, block_id="p0_b1", text="chiral"))
        session.add(
            TaskBlock(
                task_id=task_id,
                block_id="p0_b2",
                text="measures",
                translated="测度",
            )
        )
        session.commit()

    got = translate_pack.get_progress(_ctx(), {"task_id": task_id})
    assert got.data["status"] == "in_progress"
    assert got.data["progress"] == 0.42
    assert got.data["stage"] == "translating"
    assert got.data["eta_seconds"] == 90
    assert got.data["tier"] == "medium"
    assert got.data["source_lang"] == "en"
    assert got.data["target_lang"] == "zh"
    # 块数顺带算：2 块里 1 块有译文
    assert got.data["blocks"] == 2
    assert got.data["translated_blocks"] == 1
    assert "42%" in got.note

    _cleanup(task_id)


def test_get_progress_hides_other_users_task() -> None:
    """② 别人的任务读不到（文案不能暴露"它其实存在"）。"""
    task_id = _make_task(status="completed", progress=1.0)
    with SessionLocal() as session:
        task = session.get(Task, task_id)
        assert task is not None
        task.user_id = TEST_USER_ID + 999
        session.commit()

    got = translate_pack.get_progress(_ctx(), {"task_id": task_id})
    assert "找不到" in str(got.data)
    assert "chem_arXiv.pdf" not in str(got.data)

    _cleanup(task_id)


def test_request_retranslate_without_confirm_changes_nothing() -> None:
    """③ 不带 confirm：只解释，**status 一个字都不改**。"""
    task_id = _make_task(status="failed", progress=0.5, stage="translating")

    got = translate_pack.request_retranslate(_ctx(), {"task_id": task_id})
    assert "确认" in str(got.data)
    assert "重试" in str(got.data)
    assert _status_of(task_id) == "failed"
    with SessionLocal() as session:
        task = session.get(Task, task_id)
        assert task is not None
        assert task.progress == 0.5, "没确认时连进度都不许清"

    # `confirm: false` 与"不传"等价，同样不许改
    again = translate_pack.request_retranslate(
        _ctx(), {"task_id": task_id, "confirm": False}
    )
    assert "确认" in str(again.data)
    assert _status_of(task_id) == "failed"

    _cleanup(task_id)


def test_request_retranslate_with_confirm_requeues() -> None:
    """④ 真确认了才置回待处理（旧块等 worker 认领时自己清）。"""
    task_id = _make_task(
        status="failed",
        progress=0.7,
        eta_seconds=30,
        stage="translating",
        error_message="引擎挂了",
    )

    got = translate_pack.request_retranslate(
        _ctx(), {"task_id": task_id, "confirm": True}
    )
    assert got.data["status"] == "pending"
    assert got.data["previous_status"] == "failed"
    with SessionLocal() as session:
        task = session.get(Task, task_id)
        assert task is not None
        assert task.status == "pending"
        assert task.progress == 0.0
        assert task.stage is None
        assert task.eta_seconds is None
        assert task.error_message is None

    _cleanup(task_id)


def test_handlers_tolerate_weird_args() -> None:
    """⑤ args 是 None / 不是 dict / id 是字符串，都不许抛异常。"""
    assert "没有指定" in str(translate_pack.get_progress(_ctx(), None).data)
    assert "没有指定" in str(translate_pack.get_progress(_ctx(), ["x"]).data)
    assert "没有指定" in str(translate_pack.get_progress(_ctx(), "task_id=1").data)
    # confirm 是字符串 "true" 不算确认（宁可多问一句，也不能误改库）
    task_id = _make_task(status="failed", progress=0.5)
    got = translate_pack.request_retranslate(
        _ctx(), {"task_id": str(task_id), "confirm": "true"}
    )
    assert "确认" in str(got.data)
    assert _status_of(task_id) == "failed"

    _cleanup(task_id)
