"""「读懂」收尾校验（verify_read）的单测。

约定：不查库、不用 tmp_path，直接构造 ToolContext 与 AskAnswer。
"""

from __future__ import annotations

from app.agent.contracts import ToolContext
from app.agent.outputs import AskAnswer
from app.agent.verify_read import locatable_rate, verify_sources


def _ctx() -> ToolContext:
    return ToolContext(
        db=None,
        user_id=1,
        scene_id="read_ask",
        scope={"task_id": 7},
    )


def test_drops_malformed_ids_and_names_them() -> None:
    """格式不对的剔掉，note 里点名数量与坏编号。"""
    output = AskAnswer(
        answer="看原文即可。",
        source_block_ids=["p0_b4", "第3段", "page1"],
    )
    kept, notes = verify_sources(_ctx(), output)
    assert kept.source_block_ids == ["p0_b4"]
    bad = [note for note in notes if "格式不对" in note]
    assert bad
    assert "2 个" in bad[0]
    assert "第3段" in bad[0]
    assert "page1" in bad[0]


def test_valid_ids_keep_order_and_dedupe() -> None:
    """合法块号保序去重；率按原始给出数算。"""
    output = AskAnswer(
        answer="两页的结论一致。",
        source_block_ids=["p2_b1", "p0_b4", "p2_b1", "p10_b2"],
    )
    kept, notes = verify_sources(_ctx(), output)
    assert kept.source_block_ids == ["p2_b1", "p0_b4", "p10_b2"]
    assert any("75%（3/4）" in note for note in notes)


def test_caps_at_twenty_sources() -> None:
    """超过 20 个截断，并说明截掉几个。"""
    ids = [f"p0_b{index}" for index in range(25)]
    output = AskAnswer(answer="出处很多。", source_block_ids=ids)
    kept, notes = verify_sources(_ctx(), output)
    assert kept.source_block_ids == ids[:20]
    assert any("截断 5 个" in note for note in notes)
    assert any("80%（20/25）" in note for note in notes)


def test_long_answer_without_sources_gets_reminder() -> None:
    """空出处 + 长答案：提醒没给出处，但不清空答案。"""
    answer = "这段回答在讲具体内容。" * 8
    output = AskAnswer(answer=answer, source_block_ids=[])
    kept, notes = verify_sources(_ctx(), output)
    assert any("没有给出处" in note for note in notes)
    assert kept.answer == answer
    assert kept.source_block_ids == []
    assert not any("100%" in note for note in notes)


def test_short_answer_without_sources_stays_quiet() -> None:
    """空出处 + 短答案：不啰嗦，一条 note 都不给。"""
    output = AskAnswer(answer="不确定。", source_block_ids=[])
    _, notes = verify_sources(_ctx(), output)
    assert notes == []


def test_zero_sources_rate_is_none_not_one() -> None:
    """原始为 0 时率是 None，绝不当成 100%。"""
    assert locatable_rate(0, 0) is None
    assert locatable_rate(0, 0) != 1.0
    _, notes = verify_sources(
        _ctx(), AskAnswer(answer="短", source_block_ids=[])
    )
    assert not any("100%" in note for note in notes)


def test_invalid_only_sources_rate_is_zero() -> None:
    """全是不合格编号时，保留 0 个、率写 0%。"""
    output = AskAnswer(answer="看这里。", source_block_ids=["第3段"])
    kept, notes = verify_sources(_ctx(), output)
    assert kept.source_block_ids == []
    assert any("0%（0/1）" in note for note in notes)


def test_bare_block_id_in_answer_is_flagged() -> None:
    """正文写了块号却没登记：只提醒，不改文本。"""
    answer = "按 p0_b4 的说法，结论成立。"
    output = AskAnswer(answer=answer, source_block_ids=[])
    kept, notes = verify_sources(_ctx(), output)
    hit = [
        note
        for note in notes
        if "正文里提到了块号但没登记为出处" in note
    ]
    assert hit
    assert "p0_b4" in hit[0]
    assert kept.answer == answer


def test_registered_block_id_in_answer_is_not_flagged() -> None:
    """正文块号已经登记过，就不再提醒。"""
    output = AskAnswer(
        answer="按 p0_b4 的说法，结论成立。",
        source_block_ids=["p0_b4"],
    )
    _, notes = verify_sources(_ctx(), output)
    assert not any("没登记为出处" in note for note in notes)


def test_returns_new_object_and_leaves_input_alone() -> None:
    """返回新对象，原 output 的字段一个字都不能变。"""
    original = AskAnswer(
        answer="原答案",
        source_block_ids=["p0_b4", "bad"],
    )
    result, _ = verify_sources(_ctx(), original)
    assert result is not original
    assert original.source_block_ids == ["p0_b4", "bad"]
    assert original.answer == "原答案"
    assert result.source_block_ids == ["p0_b4"]
    assert result.answer == "原答案"
