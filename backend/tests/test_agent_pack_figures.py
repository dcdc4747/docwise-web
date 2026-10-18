"""图注工具包（figures）的用例：列图注、读图注与前后块、未知块、归属。

这些用例**不用 db_session fixture**：自己在 `SessionLocal` 里造数，跑完清理。
不调模型、不碰网络——两个工具本来就是确定性的。
"""

from __future__ import annotations

from helpers import TEST_USER_ID

from app.agent.contracts import ToolContext
from app.agent.packs import figures
from app.db import SessionLocal
from app.models import Task, TaskBlock

# 一篇小样本：正文 + 三条图注（前两条有译文、第三条没有）+ 一条"提到图"的正文。
# `Fig. 7 shows …` 只是**提到**图，`classify` 会把它判成正文——这块必须留在清单外。
_SAMPLE = [
    ("p0_b0", "Figure 1 shows the whole apparatus at a glance.", None),
    (
        "p1_b0",
        "FIG. 1. Chiral measures of the rotational wavepacket.",
        "图 1. 旋转波包的手性测度。",
    ),
    ("p1_b1", "The measured lifetimes agree with the model.", None),
    (
        "p2_b0",
        "TABLE 2. Measured lifetimes for all samples.",
        "表 2. 所有样本的实测寿命。",
    ),
    ("p2_b1", "Fig. 7 shows both local measures in one frame.", None),
    ("p4_b0", "Figure 3: Overview of the pipeline.", None),
]


def _ctx(user_id: int = TEST_USER_ID) -> ToolContext:
    return ToolContext(db=None, user_id=user_id, scene_id="read_ask", scope={})


def _make_task(
    blocks: list[tuple[str, str, str | None]],
    *,
    user_id: int = TEST_USER_ID,
) -> int:
    """直接入库建一篇文献与它的块，返回 task_id。"""
    with SessionLocal() as session:
        task = Task(user_id=user_id, filename="figures.pdf", status="completed")
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


# ============================================================ ① 列图注


def test_list_figures_finds_captions_in_block_order() -> None:
    task_id = _make_task(_SAMPLE)
    try:
        got = figures.list_figures(_ctx(), {"task_id": task_id})

        assert [item["block_id"] for item in got.data] == [
            "p1_b0",
            "p2_b0",
            "p4_b0",
        ]
        assert [item["kind"] for item in got.data] == ["caption"] * 3
        # 有译文用译文，没有就用原文
        assert got.data[0]["text"] == "图 1. 旋转波包的手性测度。"
        assert got.data[1]["text"] == "表 2. 所有样本的实测寿命。"
        assert got.data[2]["text"] == "Figure 3: Overview of the pipeline."
        # 块号 pN_bM → 第 N+1 页；提到图的正文（p2_b1）不在清单里
        assert [item["page_hint"] for item in got.data] == [2, 3, 5]
        assert "3 条图注" in got.note

        # args 容错：字符串 task_id 也认（模型常把数字写成字符串）
        as_str = figures.list_figures(_ctx(), {"task_id": str(task_id)})
        assert [item["block_id"] for item in as_str.data] == [
            "p1_b0",
            "p2_b0",
            "p4_b0",
        ]
    finally:
        _cleanup(task_id)


# ============================================================ ② 前后块


def test_read_figure_returns_caption_with_one_neighbor_each_side() -> None:
    task_id = _make_task(_SAMPLE)
    try:
        got = figures.read_figure(_ctx(), {"task_id": task_id, "block_id": "p1_b0"})

        assert got.data["caption"] == {
            "block_id": "p1_b0",
            "text": "图 1. 旋转波包的手性测度。",
        }
        # 前一块（上一页末尾的正文）与后一块（紧跟其后的正文）都带上
        assert got.data["before"]["block_id"] == "p0_b0"
        assert got.data["after"]["block_id"] == "p1_b1"
        assert got.data["after"]["text"] == (
            "The measured lifetimes agree with the model."
        )
        assert got.data["page_hint"] == 2
        assert "第 2 页" in got.note
    finally:
        _cleanup(task_id)


def test_read_figure_at_document_edges_has_no_neighbor() -> None:
    task_id = _make_task(
        [
            ("p0_b0", "FIG. 1. Only a caption here.", "图 1. 这里只有图注。"),
            ("p0_b1", "Body paragraph.", None),
        ]
    )
    try:
        head = figures.read_figure(_ctx(), {"task_id": task_id, "block_id": "p0_b0"})
        assert head.data["before"] is None
        assert head.data["after"] == {
            "block_id": "p0_b1",
            "text": "Body paragraph.",
        }

        # 读正文块也不抛异常：照读，但如实说它"不是图注"
        tail = figures.read_figure(_ctx(), {"task_id": task_id, "block_id": "p0_b1"})
        assert tail.data["after"] is None
        assert "不是图注" in tail.note
    finally:
        _cleanup(task_id)


# ============================================================ ③ 未知块


def test_read_figure_unknown_block_reports_error() -> None:
    task_id = _make_task(_SAMPLE)
    try:
        got = figures.read_figure(_ctx(), {"task_id": task_id, "block_id": "p9_b9"})
        assert "没有块 p9_b9" in got.data["error"]
        assert "list_figures" in got.data["error"]

        # 没给 / 给了奇怪类型：一句人话，不是异常
        assert figures.read_figure(_ctx(), {"task_id": task_id}).data == {
            "error": "没有指定 block_id"
        }
        assert figures.read_figure(
            _ctx(), {"task_id": task_id, "block_id": 3}
        ).data == {"error": "没有指定 block_id"}
    finally:
        _cleanup(task_id)


# ============================================================ ④ 归属


def test_other_users_document_is_not_found() -> None:
    other_id = _make_task(_SAMPLE, user_id=TEST_USER_ID + 999)
    try:
        listed = figures.list_figures(_ctx(), {"task_id": other_id})
        assert listed.data == []
        assert "找不到" in listed.note

        read = figures.read_figure(
            _ctx(), {"task_id": other_id, "block_id": "p1_b0"}
        )
        assert "找不到" in read.data["error"]

        # args 容错：不是 dict 也不能抛异常
        weird = figures.list_figures(_ctx(), ["not", "a", "dict"])
        assert weird.data == []
    finally:
        _cleanup(other_id)


# ============================================================ ⑤ 空态


def test_document_without_captions_is_honest() -> None:
    task_id = _make_task(
        [
            ("p0_b0", "A plain paragraph without any figure.", None),
            ("p0_b1", "Another plain paragraph in the same document.", None),
        ]
    )
    try:
        got = figures.list_figures(_ctx(), {"task_id": task_id})
        assert got.data == []
        assert "没有识别到图注" in got.note
        assert "扫描件" in got.note
    finally:
        _cleanup(task_id)


def test_task_without_blocks_says_processing() -> None:
    task_id = _make_task([])
    try:
        got = figures.list_figures(_ctx(), {"task_id": task_id})
        assert got.data == []
        assert "还没有可读的块" in got.note
    finally:
        _cleanup(task_id)
