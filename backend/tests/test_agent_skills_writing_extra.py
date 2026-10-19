"""写作板块新增的 3 个技能：数量、正文长度、索引预算、板块隔离。

为什么单独一个文件：新增技能最容易出的问题是「只加了文件没进索引」
或者「索引悄悄变长」。这里把能算的部分钉住。
"""

from __future__ import annotations

from app.agent.contracts import ToolContext
from app.agent.packs.skills import use_skill
from app.agent.skills import load_skills, skill_index_prompt, skills_for

WRITE_SKILLS = {
    "journal-format",
    "typesetting-rules",
    "revision-protocol",
    "citation-placement",
    "abstract-writing",
    "table-figure-rules",
}
NEW_SKILLS = {
    "citation-placement",
    "abstract-writing",
    "table-figure-rules",
}
MIN_BODY = 600
MAX_BODY = 2000


def _ctx(scene_id: str = "write_compose") -> ToolContext:
    return ToolContext(db=None, user_id=1, scene_id=scene_id, scope={})


def test_write_scene_now_has_six_skills() -> None:
    """写作板块 = 原 3 个 + 新 3 个，一个不多一个不少。"""
    names = {skill.name for skill in skills_for("write_compose")}
    assert names == WRITE_SKILLS
    assert NEW_SKILLS <= names


def test_new_skill_bodies_are_substantial() -> None:
    """正文要够长才有判据，也不能长到撑爆一轮上下文。"""
    loaded = load_skills()
    for name in sorted(NEW_SKILLS):
        body = loaded[name].body.strip()
        assert body, name
        assert MIN_BODY <= len(body) <= MAX_BODY, (name, len(body))


def test_write_index_is_six_short_lines() -> None:
    """索引是唯一进默认 prompt 的东西，必须短。"""
    index = skill_index_prompt("write_compose")
    lines = [line for line in index.splitlines() if line.startswith("- ")]
    assert len(lines) == 6
    for line in lines:
        assert len(line) <= 60, line
    assert len(index) < 600


def test_read_scene_cannot_see_new_write_skills() -> None:
    """板块隔离：读懂场景既列不出、也索引不到这 3 个新技能。"""
    read_names = {skill.name for skill in skills_for("read_ask")}
    assert not (read_names & NEW_SKILLS)
    index = skill_index_prompt("read_ask")
    for name in NEW_SKILLS:
        assert name not in index


def test_use_skill_serves_citation_placement() -> None:
    """真按写作场景取一次：正文要能拿到，且带引用判据。"""
    result = use_skill(_ctx(), {"name": "citation-placement"})
    data = result.data
    assert data["name"] == "citation-placement"
    assert data["truncated"] is False
    body = data["body"]
    assert "[n]" in body
    assert "引用" in body
    assert "已加载" in result.note


def test_each_new_skill_when_is_short() -> None:
    """`when` 会进 prompt，一条不超过 40 个汉字。"""
    loaded = load_skills()
    for name in sorted(NEW_SKILLS):
        assert len(loaded[name].when) <= 40, name
