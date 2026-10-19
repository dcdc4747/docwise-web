"""读懂板块的 6 个技能：索引、正文长度、板块隔离、按需取用。

为什么单独一个文件：技能是**内容**，内容坏了不会抛异常——
索引变长会悄悄吃掉上下文，正文太短则只剩一句空话。
这里把「可验收」的部分钉住：数量、长度、隔离、真实取用。
"""

from __future__ import annotations

from app.agent.contracts import ToolContext
from app.agent.packs.skills import use_skill
from app.agent.skills import load_skills, skill_index_prompt, skills_for

READ_SKILLS = {
    "close-reading",
    "quote-grounding",
    "term-consistency",
    "section-map",
    "cross-doc-matrix",
    "translation-audit",
}
MIN_BODY = 600
MAX_BODY = 2000


def _ctx(scene_id: str = "read_ask") -> ToolContext:
    return ToolContext(db=None, user_id=1, scene_id=scene_id, scope={})


def test_read_scene_has_exactly_six_skills() -> None:
    """读懂板块恰好这 6 个技能（多一个少一个都算内容漂移）。"""
    names = {skill.name for skill in skills_for("read_ask")}
    assert names == READ_SKILLS


def test_write_scene_does_not_see_read_skills() -> None:
    """板块隔离：`applies_to` 是硬边界，写作时翻不到精读技能。"""
    names = {skill.name for skill in skills_for("write_compose")}
    assert not (names & READ_SKILLS)


def test_read_index_is_six_short_lines() -> None:
    """索引是唯一进默认 prompt 的东西，必须短。"""
    index = skill_index_prompt("read_ask")
    assert "use_skill" in index
    lines = [line for line in index.splitlines() if line.startswith("- ")]
    assert len(lines) == 6
    for line in lines:
        assert len(line) <= 60, line
    assert len(index) < 800


def test_each_read_skill_body_is_substantial() -> None:
    """正文要够长才有指导价值，也不能长到撑爆一轮上下文。"""
    loaded = load_skills()
    for name in sorted(READ_SKILLS):
        body = loaded[name].body.strip()
        assert body, name
        assert MIN_BODY <= len(body) <= MAX_BODY, (name, len(body))


def test_each_read_skill_when_is_short() -> None:
    """`when` 会进 prompt，一条不超过 40 个汉字。"""
    loaded = load_skills()
    for name in sorted(READ_SKILLS):
        assert len(loaded[name].when) <= 40, name


def test_use_skill_serves_close_reading() -> None:
    """真按 read_ask 场景取一次：正文要能拿到，且带关键判据。"""
    result = use_skill(_ctx(), {"name": "close-reading"})
    data = result.data
    assert data["name"] == "close-reading"
    assert data["truncated"] is False
    assert "block_id" in data["body"]
    assert "已加载" in result.note


def test_use_skill_rejects_write_skill_in_read_scene() -> None:
    """反向：读懂场景拿不到写作技能，note 要说清是板块边界。"""
    result = use_skill(_ctx(), {"name": "journal-format"})
    assert "不是这个板块" in result.note
    assert result.data["applies_to"] == ["write_compose"]
