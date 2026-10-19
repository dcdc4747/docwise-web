"""Skill 层（2026-10-19）：索引、按板块隔离、按需取正文、超长截断。

为什么单独一个文件：这一层是"板块专业化"的地基。它坏掉的表现是**静默的**——
索引变长会悄悄吃掉上下文，跨板块可见会让写作时去翻"怎么精读"，
正文不截断则一个大 skill 就能撑爆一轮请求。
"""

from __future__ import annotations

import json

from app.agent.contracts import ToolContext
from app.agent.packs.skills import PACK, use_skill
from app.agent.skills import (
    MAX_BODY_CHARS,
    load_skills,
    skill_index_prompt,
    skills_for,
)


def _ctx(scene_id: str = "write_compose") -> ToolContext:
    return ToolContext(db=None, user_id=1, scene_id=scene_id, scope={})


def test_three_write_skills_are_loaded() -> None:
    names = set(load_skills())
    assert {"journal-format", "typesetting-rules", "revision-protocol"} <= names


def test_index_is_short_and_only_names_what_to_use() -> None:
    """索引必须短——它是唯一进默认 prompt 的东西（正文按需取）。"""
    index = skill_index_prompt("write_compose")
    assert "use_skill" in index
    # 每条一行、一行不超过一句
    lines = [line for line in index.splitlines() if line.startswith("- ")]
    assert len(lines) == 6  # 原 3 个写作技能 + 新增 3 个
    for line in lines:
        assert len(line) <= 60, line  # 中文按字符算，60 已经很宽松
    assert len(index) < 400


def test_skills_are_isolated_per_scene() -> None:
    """板块隔离：`applies_to` 是硬边界（两边互相拿不到）。"""
    read_names = {skill.name for skill in skills_for("read_ask")}
    assert "close-reading" in read_names
    assert "journal-format" not in read_names

    write_names = {skill.name for skill in skills_for("write_compose")}
    assert "journal-format" in write_names
    assert "close-reading" not in write_names
    assert "journal-format" not in skill_index_prompt("read_ask")


def test_use_skill_returns_body_and_title() -> None:
    result = use_skill(_ctx(), {"name": "journal-format"})
    assert "投稿体例" in str(result.data["title"]) or "体例" in result.data["title"]
    assert "Index Terms" in result.data["body"]  # IEEE 的硬要求在里面
    assert result.data["truncated"] is False
    assert "已加载" in result.note


def test_use_skill_rejects_other_scene_and_unknown_names() -> None:
    other = use_skill(_ctx("read_ask"), {"name": "journal-format"})
    assert "不是这个板块" in other.note
    assert other.data["applies_to"] == ["write_compose"]

    missing = use_skill(_ctx(), {"name": "no-such-skill"})
    assert "没有这个技能" in missing.note
    assert "journal-format" in missing.data["available"]

    empty = use_skill(_ctx(), {})
    assert "要给技能名" in empty.note


def test_long_skill_body_is_truncated_with_disclosure(monkeypatch) -> None:
    """超过上限要截断，并且如实标注（不假装完整）。"""
    too_long = "啊" * (MAX_BODY_CHARS + 50)
    declared = {
        "skills": [
            {
                "name": "huge",
                "title": "超长技能",
                "applies_to": ["write_compose"],
                "when": "测试用",
            }
        ]
    }

    def fake_read(path) -> str:
        if path.name == "_index.json":
            return json.dumps(declared, ensure_ascii=False)
        if path.name == "SKILL.md":
            return too_long
        return ""

    monkeypatch.setattr("app.agent.skills._read_text", fake_read)
    loaded = load_skills()["huge"]
    assert len(loaded.body) == MAX_BODY_CHARS + 50
    assert loaded.when == "测试用"

    # 工具层按上限截断，并留下「已截断」的说明
    monkeypatch.setattr(
        "app.agent.packs.skills.load_skills", lambda: {"huge": loaded}
    )
    result = use_skill(_ctx(), {"name": "huge"})
    assert result.data["truncated"] is True
    assert "已截断" in result.data["body"]


def test_pack_exposes_exactly_one_tool() -> None:
    """一个 skill 包只该有 `use_skill` 一个工具——工具预算很紧（写作正好 15 个）。"""
    assert PACK.name == "skills"
    assert [spec.name for spec in PACK.tools] == ["use_skill"]
