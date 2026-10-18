"""记忆工具包（`memory` pack）的只读用例。

三条底线：
1. 有偏好时能读出来（没设置时是空 dict + 如实 note）；
2. 记忆按关键词过滤生效（中文命中译名、英文命中原文）；
3. 别人的记忆读不到（按 `ctx.user_id` 过滤）。

⚠️ 不用 `db_session` fixture：自己开 `SessionLocal()` 造数据，并在用例末尾清理。
"""

from __future__ import annotations

import json

from helpers import TEST_USER_ID
from sqlalchemy import select

from app.agent.contracts import ToolContext
from app.agent.packs import memory as memory_pack
from app.db import SessionLocal
from app.models import MemoryItem, UserPrefs

_OTHER_USER_ID = TEST_USER_ID + 1


def _ctx(user_id: int = TEST_USER_ID) -> ToolContext:
    return ToolContext(db=None, user_id=user_id, scene_id="read_ask", scope={})


def _clean_prefs(user_id: int = TEST_USER_ID) -> None:
    with SessionLocal() as session:
        row = session.scalar(select(UserPrefs).where(UserPrefs.user_id == user_id))
        if row is not None:
            session.delete(row)
            session.commit()


def _clean_memories(user_id: int = TEST_USER_ID) -> None:
    with SessionLocal() as session:
        rows = session.scalars(
            select(MemoryItem).where(MemoryItem.user_id == user_id)
        ).all()
        for row in rows:
            session.delete(row)
        session.commit()


def _add_memory(user_id: int, kind: str, source: str, target: str) -> None:
    with SessionLocal() as session:
        session.add(
            MemoryItem(
                user_id=user_id,
                kind=kind,
                source=source,
                target=target,
            )
        )
        session.commit()


def test_pack_registers_both_tools() -> None:
    from app.agent import registry

    registry.reset_cache()
    assert memory_pack.PACK.name == "memory"
    assert {tool.name for tool in memory_pack.PACK.tools} == {
        "get_preferences",
        "search_memories",
    }
    assert "memory" in registry.packs()


def test_get_preferences_reads_saved_values() -> None:
    _clean_prefs()
    with SessionLocal() as session:
        session.add(
            UserPrefs(
                user_id=TEST_USER_ID,
                payload=json.dumps(
                    {
                        "defaultView": "dual",
                        "tier": "fast",
                        "readingSize": "large",
                    },
                    ensure_ascii=False,
                ),
            )
        )
        session.commit()
    try:
        got = memory_pack.get_preferences(_ctx())
        assert got.data == {
            "defaultView": "dual",
            "tier": "fast",
            "readingSize": "large",
        }
        assert got.note == "3 项偏好"
    finally:
        _clean_prefs()


def test_get_preferences_empty_when_not_set() -> None:
    _clean_prefs()
    got = memory_pack.get_preferences(_ctx())
    assert got.data == {}
    assert got.note == "还没有设置偏好"


def test_search_memories_filters_by_keyword() -> None:
    _clean_memories()
    _add_memory(TEST_USER_ID, "term", "chiral", "手性")
    _add_memory(TEST_USER_ID, "term", "sparse", "稀疏")
    _add_memory(TEST_USER_ID, "cite", "default", "author-year")
    try:
        by_target = memory_pack.search_memories(_ctx(), {"query": "手性"})
        assert [item["source"] for item in by_target.data] == ["chiral"]
        assert by_target.data[0]["kind"] == "term"
        assert by_target.data[0]["text"] == "chiral → 手性"
        assert by_target.data[0]["created_at"].endswith("+00:00")

        by_source = memory_pack.search_memories(_ctx(), {"query": "chiral"})
        assert [item["target"] for item in by_source.data] == ["手性"]

        missed = memory_pack.search_memories(_ctx(), {"query": "不存在的词"})
        assert missed.data == []
        assert "没有匹配" in missed.note
    finally:
        _clean_memories()


def test_search_memories_ignores_other_users() -> None:
    _clean_memories(_OTHER_USER_ID)
    _add_memory(_OTHER_USER_ID, "term", "chiral", "别人的手性")
    try:
        got = memory_pack.search_memories(_ctx(), {"query": "手性"})
        assert got.data == []
        assert "没有匹配" in got.note
    finally:
        _clean_memories(_OTHER_USER_ID)


def test_get_preferences_ignores_other_users() -> None:
    _clean_prefs()
    with SessionLocal() as session:
        session.add(
            UserPrefs(
                user_id=_OTHER_USER_ID,
                payload=json.dumps({"tier": "fast"}, ensure_ascii=False),
            )
        )
        session.commit()
    try:
        got = memory_pack.get_preferences(_ctx())
        assert got.data == {}
        assert got.note == "还没有设置偏好"
    finally:
        _clean_prefs(_OTHER_USER_ID)


def test_search_memories_is_read_only() -> None:
    """查记忆不许改 `hits`（那是 `resolve_active` 的账，不是只读查询该做的事）。"""
    _clean_memories()
    _add_memory(TEST_USER_ID, "term", "chiral", "手性")
    try:
        memory_pack.search_memories(_ctx(), {"query": "chiral"})
        with SessionLocal() as session:
            row = session.scalar(
                select(MemoryItem).where(MemoryItem.user_id == TEST_USER_ID)
            )
            assert row.hits == 0
    finally:
        _clean_memories()


def test_search_memories_tolerates_missing_args() -> None:
    _clean_memories()
    _add_memory(TEST_USER_ID, "term", "chiral", "手性")
    try:
        assert len(memory_pack.search_memories(_ctx(), None).data) == 1
        assert len(memory_pack.search_memories(_ctx(), {}).data) == 1
        assert len(memory_pack.search_memories(_ctx(), {"limit": "坏值"}).data) == 1
        assert len(memory_pack.search_memories(_ctx(), {"limit": 0}).data) == 1
    finally:
        _clean_memories()
