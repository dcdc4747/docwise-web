"""M7 记忆的「请求前注入」（任务卡 D8 里那个 `_enrich()`）的测试。

盯七件事（每条都对应一个"真会发生"的错法）：

1. ⭐ **没有记忆时一个字节都不许变**：`enrich()` 回空串，提示词与之前完全一致
   （这条最重要——不能让 M7 把问答/导读的既有行为弄坏）；
2. ⭐ **只注入这篇里真的出现过的术语**：不出现的塞进去纯属浪费预算、还会干扰模型；
3. ⭐ **有上限**：记忆会长大，提示词预算是有限的（`MAX_TERMS`）；
4. ⭐ **引用格式偏好带人话标签**（`author-year` → "作者-年份"），别把标识裸塞给模型；
5. ⭐ **绝不改出处口径**：注入的那段里必须明确写着
   "`source_block_ids` 仍必须确实支撑结论"；
6. ⭐ **真的接到两条链路上**：`answer_question` / `extract_understanding`
   的 system 提示词里确实出现了记忆（不是"函数写了没人调"）；
7. ⭐ **问答接口端到端**：库里存了一条术语 → 提问时模型真收到了它
   （走真 `answer_question`，只把 `_chat` 换成假函数）。

⚠️ 不用 `tmp_path`（AGENTS.md：受限环境不可写）。
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from helpers import TEST_USER_ID
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.memory import MAX_TERMS, enrich, resolve_active
from app.models import MemoryItem, Task, TaskBlock

client = TestClient(app)


def _add_term(source: str, target: str, *, enabled: bool = True) -> None:
    with SessionLocal() as session:
        session.add(
            MemoryItem(
                user_id=TEST_USER_ID,
                kind="term",
                source=source,
                target=target,
                enabled=enabled,
            )
        )
        session.commit()


# ---------------------------------------------------------------- enrich（纯函数）


def test_没有记忆时一个字节都不加():
    """⭐ 默认行为必须一字不差（M7 不许影响没开记忆的人）。"""
    assert enrich({}, None, "随便一段原文 chiral") == ""
    assert enrich(None, None, "") == ""
    # 停用之后传进来的是空 dict，同样不该拼任何东西
    assert enrich({}, None, "corpus") == ""


def test_只注入这篇里出现过的术语():
    """⭐ 不出现的术语不塞进去（省预算，也避免干扰模型）。"""
    hint = enrich({"chiral": "手性", "entropy": "熵"}, None, "这篇文献讲 chiral 分子。")
    assert "chiral → 手性" in hint
    assert "entropy" not in hint, "把这篇里没出现的术语也注入了"
    assert "熵" not in hint


def test_译法出现在中文正文里也算命中():
    """⭐ 这条是踩出来的：外文文献发给模型的是**中文译文**（"手性分子"），
    库里记的却是原文词（`chiral`）。只比原文词的话这条路永远匹配不上。"""
    hint = enrich({"chiral": "手性"}, None, "这是一篇讲手性分子的文献。")
    assert "chiral → 手性" in hint


def test_原文词与译法都没有时不注入():
    hint = enrich({"chiral": "手性"}, None, "这是一篇讲晶体生长的文献。")
    assert "术语偏好" not in hint


def test_匹配不区分大小写():
    hint = enrich({"Chiral": "手性"}, None, "a chiral molecule")
    assert "手性" in hint


def test_库里术语全都对不上时不注入术语段():
    hint = enrich({"chiral": "手性"}, "numeric", "这篇讲的是别的题目。")
    assert "术语偏好" not in hint
    # 但引用格式该照注入（它跟正文用词无关）
    assert "数字编号" in hint


def test_有上限():
    """⭐ 记忆会长大，提示词预算有限：最多注入 MAX_TERMS 条。"""
    terms = {f"w{i}": f"词{i}" for i in range(MAX_TERMS + 20)}
    corpus = " ".join(terms)
    hint = enrich(terms, None, corpus)
    assert hint.count("→") == MAX_TERMS


def test_引用格式给人话标签():
    assert "作者-年份" in enrich({}, "author-year", "")
    assert "数字编号" in enrich({}, "numeric", "")
    # 没登记的标识就原样给（不许编一个人话出来）
    assert "hanging" in enrich({}, "hanging", "")


def test_永远带出处口径那句():
    """⭐ 注入不许让模型以为"有记忆就不用给出处了"。"""
    for hint in (
        enrich({"chiral": "手性"}, None, "chiral"),
        enrich({}, "numeric", ""),
    ):
        assert "source_block_ids" in hint
        assert "仍必须确实支撑结论" in hint


# ------------------------------------------------------------ resolve_active（取数）


def test_没记过就是空的并且不计数():
    with SessionLocal() as session:
        data = resolve_active(session, TEST_USER_ID)
    assert data == {"terms": {}, "cite": None}


def test_只取启用的并计数():
    _add_term("chiral", "手性")
    _add_term("停用的", "不该取到", enabled=False)
    with SessionLocal() as session:
        session.add(
            MemoryItem(
                user_id=TEST_USER_ID, kind="cite", source="default", target="numeric"
            )
        )
        session.commit()
        data = resolve_active(session, TEST_USER_ID)
    assert data["terms"] == {"chiral": "手性"}
    assert data["cite"] == "numeric"

    with SessionLocal() as session:
        rows = {r.source: r.hits for r in session.scalars(select(MemoryItem)).all()}
    assert rows["chiral"] == 1
    assert rows["停用的"] == 0


# ---------------------------------------------------------------- 真接到两条链路


def _capture_chat(monkeypatch, payload: str) -> dict:
    captured: dict = {}

    def fake_chat(messages, max_tokens=2000, temperature=0.2):
        captured["messages"] = messages
        return payload

    monkeypatch.setattr("app.llm._chat", fake_chat)
    return captured


def test_问答的_system_提示词里真的有记忆(monkeypatch):
    captured = _capture_chat(
        monkeypatch, json.dumps({"answer": "答", "source_block_ids": ["b1"]})
    )
    from app.llm import answer_question

    answer_question(
        [("b1", "chiral 分子")],
        "这篇讲什么",
        memory_hint=enrich({"chiral": "手性"}, None, "chiral 分子"),
    )
    system = captured["messages"][0]
    assert system["role"] == "system"
    assert "chiral → 手性" in system["content"]


def test_问答没有记忆时提示词与原来一致(monkeypatch):
    """⭐ 这条守"默认行为不变"：system 就是原来那一整段，没多一个字节。"""
    captured = _capture_chat(
        monkeypatch, json.dumps({"answer": "答", "source_block_ids": ["b1"]})
    )
    from app.llm import _QA_SYSTEM_PROMPT, answer_question

    answer_question([("b1", "chiral 分子")], "这篇讲什么")
    assert captured["messages"][0]["content"] == _QA_SYSTEM_PROMPT


def test_导读的_system_提示词里真的有记忆(monkeypatch):
    captured = _capture_chat(
        monkeypatch,
        json.dumps(
            {
                "research_question": {"text": "问题", "source_block_ids": ["b1"]},
                "method": {"text": "方法", "source_block_ids": ["b1"]},
                "conclusion": {"text": "结论", "source_block_ids": ["b1"]},
                "innovation": {"text": "创新", "source_block_ids": ["b1"]},
                "contribution": {"text": "贡献", "source_block_ids": ["b1"]},
                "terms": [],
            }
        ),
    )
    from app.llm import extract_understanding

    extract_understanding(
        [("b1", "chiral 分子")],
        memory_hint=enrich({"chiral": "手性"}, "author-year", "chiral 分子"),
    )
    system = captured["messages"][0]["content"]
    assert "chiral → 手性" in system
    assert "作者-年份" in system


def test_问答接口端到端把记忆喂进模型(monkeypatch):
    """⭐ 库里存一条 → 走真 `answer_question` → 模型收到的 system 里有它。"""
    _add_term("chiral", "手性")

    with SessionLocal() as session:
        task = Task(user_id=TEST_USER_ID, filename="m.pdf", status="completed")
        session.add(task)
        session.commit()
        task_id = task.id
        session.add(
            TaskBlock(
                task_id=task_id,
                block_id="p0_b1",
                text="chiral molecule",
                translated="手性分子",
            )
        )
        session.commit()

    captured = _capture_chat(
        monkeypatch,
        json.dumps({"answer": "讲的是手性分子。", "source_block_ids": ["p0_b1"]}),
    )
    res = client.post(f"/api/tasks/{task_id}/ask", json={"question": "这篇讲什么"})
    assert res.status_code == 200, res.text
    system = captured["messages"][0]["content"]
    assert "chiral → 手性" in system, "接口没把记忆传进提示词"

    # 而且记忆的命中计数 +1（"这条真被用上过几次"）
    with SessionLocal() as session:
        row = session.scalars(
            select(MemoryItem).where(MemoryItem.source == "chiral")
        ).one()
        assert row.hits == 1


def test_导读接口端到端把记忆喂进模型(monkeypatch):
    _add_term("chiral", "手性")
    with SessionLocal() as session:
        task = Task(user_id=TEST_USER_ID, filename="m2.pdf", status="completed")
        session.add(task)
        session.commit()
        task_id = task.id
        session.add(
            TaskBlock(
                task_id=task_id,
                block_id="p0_b1",
                text="chiral molecule",
                translated=None,
            )
        )
        session.commit()

    captured = _capture_chat(
        monkeypatch,
        json.dumps(
            {
                "research_question": {"text": "问题", "source_block_ids": ["p0_b1"]},
                "method": {"text": "方法", "source_block_ids": ["p0_b1"]},
                "conclusion": {"text": "结论", "source_block_ids": ["p0_b1"]},
                "innovation": {"text": "创新", "source_block_ids": ["p0_b1"]},
                "contribution": {"text": "贡献", "source_block_ids": ["p0_b1"]},
                "terms": [{"term": "chiral", "cn": "手性", "definition": "手性"}],
            }
        ),
    )
    res = client.post(f"/api/tasks/{task_id}/understanding")
    assert res.status_code == 200, res.text
    assert "chiral → 手性" in captured["messages"][0]["content"]
