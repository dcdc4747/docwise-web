"""谎报护栏：答案自称“已改”，但没有任何写入证据时，必须被识别出来。

背景：实测模型只调了 `read_draft`，却回答“已把标题改为 X”，而 `ops` 为空、
草稿未变。用户会以为改好了——所以要有机器判据，不能靠模型自觉。
"""

from app.agent.runtime import _unbacked_claim


def test_claim_without_any_write_is_flagged() -> None:
    answer = "已把草稿 18 的标题改为「回滚验证C」，正文未动。"
    steps = [
        {"kind": "tool_call", "name": "read_draft"},
        {"kind": "tool_result", "name": "read_draft", "ok": True},
    ]
    assert _unbacked_claim(answer, steps, []) is True


def test_claim_with_successful_write_tool_is_not_flagged() -> None:
    answer = "已把标题改成「新标题」。"
    steps = [
        {"kind": "tool_call", "name": "apply_style"},
        {"kind": "tool_result", "name": "apply_style", "ok": True},
    ]
    assert _unbacked_claim(answer, steps, []) is False


def test_claim_with_failed_write_tool_is_flagged() -> None:
    answer = "已经更新了正文。"
    steps = [{"kind": "tool_result", "name": "apply_style", "ok": False}]
    assert _unbacked_claim(answer, steps, []) is True


def test_ops_present_means_write_happened() -> None:
    answer = "已写入三处改动。"
    assert _unbacked_claim(answer, [], [{"mode": "replace", "text": "x"}]) is False


def test_neutral_answer_is_not_flagged() -> None:
    assert _unbacked_claim("这篇论文讲的是稀疏线性系统的求解。", [], []) is False


def test_persisted_write_means_not_a_lie() -> None:
    # 服务端已把 ops 落库时，即便 ops 列表被清空，也不能判成谎报
    assert _unbacked_claim("已改好标题。", [], [], wrote=True) is False
