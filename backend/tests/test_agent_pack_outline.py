"""章节纲要工具包（outline）的用例：结构列表、按节读取、截断、越界、归属。

这些用例**不用 db_session fixture**：自己在 `SessionLocal` 里造数据，跑完清理。
不调模型、不碰网络——两个工具本来就是确定性的。
"""

from __future__ import annotations

from helpers import TEST_USER_ID

from app.agent.contracts import ToolContext
from app.agent.packs import outline
from app.db import SessionLocal
from app.models import Task, TaskBlock

# 一篇小样本：题名 + Abstract + 三节，正文夹在标题之间。
# 块号按约定写（`p0_b0` 起），题名判据要靠它认"首页最前面几块"。
_SAMPLE = [
    (
        "p0_b0",
        "Chiral Time Structure in Molecular Rotation Dynamics",
        "分子旋转动力学中的手性时间结构",
    ),
    ("p0_b1", "Abstract", "摘要"),
    ("p0_b2", "We study the chiral structure of rotational wavepackets.", None),
    ("p0_b3", "1. Introduction", "一、引言"),
    ("p0_b4", "Chirality plays a central role in molecular dynamics.", None),
    ("p0_b5", "2. Methods", "二、方法"),
    (
        "p0_b6",
        "We measured the orientation trajectories of the sample.",
        "我们测量了样本的取向轨迹。",
    ),
    ("p0_b7", "3. Results", "三、结果"),
    ("p0_b8", "The measured lifetimes agree with the model.", None),
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


# ============================================================ ① 列结构


def test_list_sections_finds_title_and_headings_in_block_order() -> None:
    task_id = _make_task(_SAMPLE)
    try:
        got = outline.list_sections(_ctx(), {"task_id": task_id})
        kinds = [item["kind"] for item in got.data]
        block_ids = [item["block_id"] for item in got.data]

        # 题名 + 4 个章节标题（Abstract / 1 / 2 / 3），正文块不在列表里
        assert kinds == ["title", "heading", "heading", "heading", "heading"]
        assert block_ids == ["p0_b0", "p0_b1", "p0_b3", "p0_b5", "p0_b7"]
        assert [item["index"] for item in got.data] == [0, 1, 2, 3, 4]
        # 标题文字优先用译文
        assert got.data[1]["text"] == "摘要"
        assert got.data[2]["text"] == "一、引言"
        assert "5 节" in got.note
    finally:
        _cleanup(task_id)


def test_list_sections_on_document_without_headings_is_honest() -> None:
    """没有标题就如实返回空，并说明可能是扫描件 / 结构不在块流里。"""
    task_id = _make_task(
        [
            ("p0_b0", "A plain paragraph without any heading.", None),
            ("p0_b1", "Another plain paragraph in the same document.", None),
        ],
        user_id=TEST_USER_ID,
    )
    try:
        got = outline.list_sections(_ctx(), {"task_id": task_id})
        assert got.data == []
        assert "章节标题" in got.note
        assert "扫描件" in got.note
    finally:
        _cleanup(task_id)


# ============================================================ ② 按节读取


def test_read_section_returns_range_until_next_heading() -> None:
    task_id = _make_task(_SAMPLE)
    try:
        sections = outline.list_sections(_ctx(), {"task_id": task_id}).data
        methods = next(item for item in sections if item["block_id"] == "p0_b5")

        got = outline.read_section(
            _ctx(), {"task_id": task_id, "index": methods["index"]}
        )
        assert got.data["title"] == "二、方法"
        assert got.data["truncated"] is False
        block_ids = [item["block_id"] for item in got.data["blocks"]]
        # 本节标题包含、本节正文包含、下一个标题（p0_b7）不包含
        assert block_ids == ["p0_b5", "p0_b6"]
        assert "p0_b7" not in block_ids
        # 正文给译文
        body = next(item for item in got.data["blocks"] if item["block_id"] == "p0_b6")
        assert body["text"] == "我们测量了样本的取向轨迹。"
    finally:
        _cleanup(task_id)


def test_read_section_truncates_at_6000_chars() -> None:
    long_text = "长" * 7000
    task_id = _make_task(
        [
            ("p1_b0", "一、超长一节", None),
            ("p1_b1", "original paragraph", long_text),
        ]
    )
    try:
        got = outline.read_section(_ctx(), {"task_id": task_id, "index": 0})
        assert got.data["truncated"] is True
        returned = sum(len(item["text"]) for item in got.data["blocks"])
        assert returned == 6000
        # 截断的是正文那一块，标题原样保留
        assert got.data["blocks"][0]["text"] == "一、超长一节"
        assert "6000" in got.note
    finally:
        _cleanup(task_id)


# ============================================================ ③ 越界


def test_read_section_out_of_range_reports_human_error() -> None:
    task_id = _make_task(_SAMPLE)
    try:
        for bad_index in (99, -1):
            got = outline.read_section(
                _ctx(), {"task_id": task_id, "index": bad_index}
            )
            error = got.data["error"]
            assert "越界" in error
            assert "0–4" in error
            assert str(bad_index) in error
        # 没给 index 也要是一句人话，不是 IndexError
        missing = outline.read_section(_ctx(), {"task_id": task_id})
        assert missing.data == {"error": "没有指定 index"}
    finally:
        _cleanup(task_id)


# ============================================================ ④ 归属


def test_other_users_document_is_not_found() -> None:
    other_id = _make_task(_SAMPLE, user_id=TEST_USER_ID + 999)
    try:
        listed = outline.list_sections(_ctx(), {"task_id": other_id})
        assert listed.data == []
        assert "找不到" in listed.note

        read = outline.read_section(_ctx(), {"task_id": other_id, "index": 0})
        assert "找不到" in read.data["error"]

        # args 容错：不是 dict 也不能抛异常
        weird = outline.list_sections(_ctx(), ["not", "a", "dict"])
        assert weird.data == []
    finally:
        _cleanup(other_id)
