"""LLM 输出健壮性：JSON 截断抢救 + 超长文献抽样。

由来（真实事故）：一份 56 页中文文献抽出 1489 个块，整篇喂进去后模型把五个导字段写完了、
在 terms 中途被 max_tokens 截断——整体 json.loads 失败，导读直接落库为 failed。
修法三件一起：① 提示词限长；② 输入超预算就均匀抽样；③ 整体解析失败时按字段抢救。
"""

from __future__ import annotations

import json

import pytest

from app import llm
from app.llm import _extract_json, _sample_blocks

# 真实形态的截断响应：五个字段完整，terms 在第二个条目中途断掉
TRUNCATED = """{
  "research_question": {"text": "推荐解释线索如何影响在线行为",
                        "source_block_ids": ["p1_b1", "p2_b3"]},
  "method": {"text": "三个实验，对应购前购中购后三阶段",
             "source_block_ids": ["p8_b2"]},
  "conclusion": {"text": "线索类型通过信息加工机制影响多阶段行为",
                 "source_block_ids": ["p32_b4"]},
  "innovation": {"text": "把推荐解释扩展到购前购中购后全过程",
                 "source_block_ids": ["p3_b1"]},
  "contribution": {"text": "给出线索类型与行为路径的对应关系",
                   "source_block_ids": ["p32_b5"]},
  "terms": [{"term": "算法推荐", "cn": "算法推荐", "definition": "由算法决定信息呈现"},
            {"term": "感知不确定性", "cn": "感知不确定"""

GUIDE_KEYS = (
    "research_question",
    "method",
    "conclusion",
    "innovation",
    "contribution",
)


def test_extract_json_parses_normal_payload() -> None:
    head = TRUNCATED[: TRUNCATED.rindex('"terms"')].rstrip().rstrip(",")
    data = _extract_json(head + "}")
    assert data["method"]["text"].startswith("三个实验")


def test_extract_json_salvages_fields_when_truncated() -> None:
    """整体解析不了，但字段本身完整 → 五个字段必须都能救回来（那次失败的形态）。"""
    data = _extract_json(TRUNCATED)
    assert set(data) >= set(GUIDE_KEYS)
    assert data["conclusion"]["source_block_ids"] == ["p32_b4"]
    assert data["research_question"]["source_block_ids"] == ["p1_b1", "p2_b3"]


def test_extract_json_salvages_complete_terms_only() -> None:
    """被截断的那个术语条目要丢掉，完整的要留下——半截数据不能进术语表。"""
    terms = _extract_json(TRUNCATED).get("terms") or []
    assert [t["term"] for t in terms] == ["算法推荐"]


def test_extract_json_still_raises_when_nothing_usable() -> None:
    """完全救不回来时必须抛错（由调用方落库为 failed），不能返回空壳假装成功。"""
    with pytest.raises(ValueError):
        _extract_json("这不是 JSON")


def test_extract_json_handles_fenced_output() -> None:
    inner = '{"conclusion": {"text": "结论", "source_block_ids": ["b1"]}}'
    assert _extract_json(f"```json\n{inner}\n```")["conclusion"]["text"] == "结论"


def test_sample_blocks_keeps_head_and_tail() -> None:
    """超预算按均匀抽样：首尾都要在（结论常在末尾）。"""
    blocks = [(f"p{i}_b0", "中" * 100) for i in range(1, 101)]
    selected, sampled = _sample_blocks(blocks, 1000)

    assert sampled is True
    assert len(selected) < len(blocks)
    assert selected[0] == blocks[0]
    assert selected[-1] == blocks[-1]
    assert sum(len(t) for _, t in selected) <= 2000
    # 顺序不能乱（出处要按页序读）
    pages = [int(b[0].split("_")[0][1:]) for b in selected]
    assert pages == sorted(pages)


def test_sample_blocks_noop_when_fits() -> None:
    blocks = [("p1_b0", "短"), ("p2_b0", "也很短")]
    selected, sampled = _sample_blocks(blocks, 1000)
    assert sampled is False
    assert selected == blocks


def test_extract_understanding_tells_model_when_sampled(monkeypatch) -> None:
    """抽样时要在提示词里说明"这是抽样"，否则模型会以为看的是全文而瞎下结论。"""
    captured: dict = {}

    def fake_chat(messages, max_tokens=2000, temperature=0.2):
        captured["messages"] = messages
        captured["max_tokens"] = max_tokens
        return json.dumps(
            {"conclusion": {"text": "结论", "source_block_ids": ["p1_b0"]}},
            ensure_ascii=False,
        )

    monkeypatch.setattr(llm, "_chat", fake_chat)
    monkeypatch.setattr(llm.settings, "docwise_understanding_max_chars", 500)

    blocks = [(f"p{i}_b0", "内容" * 200) for i in range(1, 51)]
    data = llm.extract_understanding(blocks)

    prompt = captured["messages"][1]["content"]
    assert "均匀抽样" in prompt
    assert "50 段" in prompt
    assert data["conclusion"]["text"] == "结论"
    # 输出上限要按配置走（那次就是给小了才截断）
    assert captured["max_tokens"] == llm.settings.docwise_understanding_max_tokens


def test_extract_understanding_no_sampling_note_when_fits(monkeypatch) -> None:
    captured: dict = {}

    def fake_chat(messages, max_tokens=2000, temperature=0.2):
        captured["messages"] = messages
        return '{"conclusion": {"text": "结论", "source_block_ids": ["p1_b0"]}}'

    monkeypatch.setattr(llm, "_chat", fake_chat)
    llm.extract_understanding([("p1_b0", "很短的正文")])
    assert "均匀抽样" not in captured["messages"][1]["content"]
