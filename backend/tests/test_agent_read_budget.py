"""读段预算守卫（read_budget）的单测。

约定：纯状态对象，不查库、不用 tmp_path。
"""

from __future__ import annotations

from app.agent.read_budget import ReadBudget

_REPEAT_NOTE = "这一段已经读过了，用之前的内容回答；确实需要重读请说明原因"


def test_first_read_is_allowed() -> None:
    """第一次读某一段：放行，note 为空。"""
    budget = ReadBudget()
    assert budget.allow("p0_b4", 120) == (True, "")


def test_second_read_of_same_key_is_denied() -> None:
    """同一 key 第二次被拒，note 明确说"读过"。"""
    budget = ReadBudget()
    budget.record("p0_b4", 120)
    allowed, note = budget.allow("p0_b4", 120)
    assert allowed is False
    assert note == _REPEAT_NOTE
    assert "读过" in note
    assert "说明原因" in note


def test_max_reads_blocks_new_keys() -> None:
    """读满 max_reads 次后，新 key 也拒。"""
    budget = ReadBudget(max_reads=2)
    for key in ("p0_b1", "p0_b2"):
        assert budget.allow(key, 10)[0] is True
        budget.record(key, 10)
    allowed, note = budget.allow("sec:3", 10)
    assert allowed is False
    assert "预算用完" in note
    assert "整理已有内容" in note


def test_max_chars_blocks_oversized_read() -> None:
    """这次的字数会撑破 max_chars：拒；刚好读满则放行。"""
    budget = ReadBudget(max_chars=100)
    budget.record("p0_b1", 80)
    allowed, note = budget.allow("p0_b2", 30)
    assert allowed is False
    assert "超出" in note
    assert "整理已有内容" in note
    assert budget.allow("p0_b2", 20) == (True, "")


def test_allow_does_not_touch_state() -> None:
    """问三次也不改状态：stats 仍是全 0。"""
    budget = ReadBudget()
    for _ in range(3):
        budget.allow("p0_b4", 100)
    assert budget.stats() == {
        "reads": 0,
        "chars": 0,
        "repeated": 0,
        "keys": [],
    }


def test_record_is_idempotent() -> None:
    """同一 key 重复 record：reads/chars 只算一次。"""
    budget = ReadBudget()
    budget.record("p0_b4", 100)
    budget.record("p0_b4", 100)
    stats = budget.stats()
    assert stats["reads"] == 1
    assert stats["chars"] == 100
    assert stats["repeated"] == 1


def test_repeated_counts_each_extra_record() -> None:
    """每多 record 一次重复 key，repeated 加一。"""
    budget = ReadBudget()
    for _ in range(3):
        budget.record("p0_b4", 100)
    stats = budget.stats()
    assert stats["repeated"] == 2
    assert stats["reads"] == 1
    assert stats["chars"] == 100


def test_zero_chars_is_recorded_as_zero() -> None:
    """chars=0 正常：算一次读，不加字数。"""
    budget = ReadBudget(max_chars=10)
    assert budget.allow("sec:0", 0) == (True, "")
    budget.record("sec:0", 0)
    stats = budget.stats()
    assert stats["reads"] == 1
    assert stats["chars"] == 0


def test_negative_chars_count_as_zero() -> None:
    """负数字符数按 0 处理，不抛异常。"""
    budget = ReadBudget()
    budget.record("p0_b4", -50)
    assert budget.stats()["chars"] == 0
    assert budget.allow("p0_b5", -10) == (True, "")


def test_keys_keep_order_and_dedupe() -> None:
    """keys 保序，重复 key 只出现一次。"""
    budget = ReadBudget()
    for key in ("p0_b4", "sec:3", "p0_b4", "p1_b2"):
        budget.record(key, 10)
    assert budget.stats()["keys"] == ["p0_b4", "sec:3", "p1_b2"]


def test_stats_keys_is_a_copy() -> None:
    """改 stats 返回的 keys 不会污染预算。"""
    budget = ReadBudget()
    budget.record("p0_b4", 10)
    keys = budget.stats()["keys"]
    keys.append("ghost")
    assert budget.stats()["keys"] == ["p0_b4"]
    assert budget.allow("ghost", 10) == (True, "")


def test_rejected_read_leaves_budget_untouched() -> None:
    """被拒的 allow 不占名额、不加字数。"""
    budget = ReadBudget(max_reads=1)
    budget.record("p0_b4", 10)
    before = budget.stats()
    assert budget.allow("p0_b5", 10)[0] is False
    assert budget.stats() == before


def test_zero_budget_allows_nothing() -> None:
    """预算为 0 时，连 0 字的读也拒。"""
    budget = ReadBudget(max_reads=0, max_chars=0)
    allowed, note = budget.allow("p0_b4", 0)
    assert allowed is False
    assert "预算用完" in note


def test_default_budget_is_six_reads() -> None:
    """默认 6 次：前 6 次放行，第 7 次拒。"""
    budget = ReadBudget()
    for index in range(6):
        key = f"p0_b{index}"
        assert budget.allow(key, 100)[0] is True
        budget.record(key, 100)
    assert budget.allow("p0_b6", 100)[0] is False


def test_default_char_budget_is_24000() -> None:
    """默认 24000 字：刚好读满放行，多 1 字就拒。"""
    budget = ReadBudget()
    budget.record("p0_b1", 23000)
    assert budget.allow("p0_b2", 1001)[0] is False
    assert budget.allow("p0_b2", 1000) == (True, "")
