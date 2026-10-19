"""记忆工具包（`memory` pack）的用例：读偏好/查记忆 + 确认后写偏好。

底线：
1. 有偏好时能读出来（没设置时是空 dict + 如实 note）；
2. 记忆按关键词过滤生效（中文命中译名、英文命中原文）；
3. 别人的记忆读不到（按 `ctx.user_id` 过滤）；
4. 写工具不带布尔 `confirm: true` 时**一行都不许写**；
5. 按 `(user_id, kind, source)` 幂等：同一条再存只改 `target`，**不动 `hits`**。

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


def _count_memories(user_id: int = TEST_USER_ID) -> int:
    with SessionLocal() as session:
        rows = session.scalars(
            select(MemoryItem).where(MemoryItem.user_id == user_id)
        ).all()
    return len(rows)


def _only_memory(user_id: int = TEST_USER_ID) -> dict:
    """取唯一一条记忆的快照（多于/少于一条都算用例失败）。"""
    with SessionLocal() as session:
        rows = session.scalars(
            select(MemoryItem).where(MemoryItem.user_id == user_id)
        ).all()
        assert len(rows) == 1, f"预期 1 条记忆，实际 {len(rows)} 条"
        row = rows[0]
        return {
            "id": row.id,
            "user_id": row.user_id,
            "kind": row.kind,
            "source": row.source,
            "target": row.target,
            "hits": row.hits,
            "enabled": bool(row.enabled),
        }


def test_pack_registers_all_tools() -> None:
    from app.agent import registry

    registry.reset_cache()
    assert memory_pack.PACK.name == "memory"
    assert {tool.name for tool in memory_pack.PACK.tools} == {
        "get_preferences",
        "search_memories",
    }

    # 写工具单独成包（读懂场景不占名额），实现仍在 memory.py
    from app.agent.packs import memory_write

    assert {tool.name for tool in memory_write.PACK.tools} == {
        "save_memory",
        "save_term_preference",
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


# ============================================================ ⑨ 写工具：确认


def test_save_memory_without_confirm_writes_nothing() -> None:
    """① 不带 confirm（含字符串 "true"）：只回 needs_confirmation，没新行。"""
    _clean_memories()
    before = _count_memories()

    for args in (
        {"kind": "term", "source": "chiral", "target": "手性"},
        {"kind": "term", "source": "chiral", "target": "手性", "confirm": False},
        {
            "kind": "term",
            "source": "chiral",
            "target": "手性",
            "confirm": "true",
        },
    ):
        got = memory_pack.save_memory(_ctx(), args)
        assert got.data["status"] == "needs_confirmation"
        assert got.data["id"] is None
        assert "确认" in got.note

    assert _count_memories() == before, "没确认就不许写库"


def test_save_memory_with_confirm_creates_row() -> None:
    """② confirm=True：字段正确，新条目的 hits 是 0。"""
    _clean_memories()
    got = memory_pack.save_memory(
        _ctx(),
        {
            "kind": "Term",
            "source": "  chiral  ",
            "target": "手性",
            "confirm": True,
        },
    )
    assert got.data["status"] == "saved"
    assert got.data["id"] is not None
    assert got.data["kind"] == "term"
    assert got.data["source"] == "chiral"
    assert got.data["target"] == "手性"
    assert got.data["enabled"] is True
    assert got.data["created"] is True

    row = _only_memory()
    assert row["user_id"] == TEST_USER_ID
    assert row["kind"] == "term"
    assert row["source"] == "chiral"
    assert row["target"] == "手性"
    assert row["enabled"] is True
    assert row["hits"] == 0, "写偏好不碰 hits，新条目应是 0"
    _clean_memories()


def test_save_memory_same_key_updates_without_new_row() -> None:
    """③ 同 (kind, source) 再存：不新增行、只改 target、hits 不被碰。"""
    _clean_memories()
    first = memory_pack.save_memory(
        _ctx(),
        {"kind": "term", "source": "chiral", "target": "手性", "confirm": True},
    )
    again = memory_pack.save_memory(
        _ctx(),
        {"kind": "term", "source": "chiral", "target": "手征", "confirm": True},
    )
    assert again.data["status"] == "saved"
    assert again.data["created"] is False
    assert again.data["id"] == first.data["id"]
    assert _count_memories() == 1, "同一 (user_id, kind, source) 不许新增行"

    row = _only_memory()
    assert row["target"] == "手征"
    assert row["hits"] == 0

    # 就算 hits 已经被真正用过（>0），覆盖译法也不许把它清零或加一
    with SessionLocal() as session:
        item = session.get(MemoryItem, first.data["id"])
        item.hits = 7
        session.commit()
    memory_pack.save_memory(
        _ctx(),
        {"kind": "term", "source": "chiral", "target": "手性", "confirm": True},
    )
    assert _only_memory()["hits"] == 7
    _clean_memories()


def test_save_term_preference_uses_same_upsert() -> None:
    """④ save_term_preference 走同一条路径：kind=term，且幂等。"""
    _clean_memories()
    pending = memory_pack.save_term_preference(
        _ctx(), {"term": "chiral", "cn": "手性"}
    )
    assert pending.data["status"] == "needs_confirmation"
    assert _count_memories() == 0

    saved = memory_pack.save_term_preference(
        _ctx(), {"term": "chiral", "cn": "手性", "confirm": True}
    )
    assert saved.data["status"] == "saved"
    assert saved.data["kind"] == "term"
    assert saved.data["source"] == "chiral"
    assert saved.data["target"] == "手性"

    # 再走 save_memory 的同一个 (kind, source)：仍是同一行，只改 target
    merged = memory_pack.save_memory(
        _ctx(),
        {"kind": "term", "source": "chiral", "target": "手征", "confirm": True},
    )
    assert merged.data["created"] is False
    assert merged.data["id"] == saved.data["id"]
    assert _count_memories() == 1
    row = _only_memory()
    assert row["kind"] == "term"
    assert row["target"] == "手征"
    assert row["hits"] == 0
    _clean_memories()


def test_save_memory_rejects_invalid_args() -> None:
    """⑤ 坏参数明确拒绝、一行不写；cite 的 source 固定成 default。"""
    _clean_memories()
    for args in (
        {"kind": "note", "source": "chiral", "target": "手性", "confirm": True},
        {"kind": "term", "source": "   ", "target": "手性", "confirm": True},
        {"kind": "term", "source": "chiral", "target": "  ", "confirm": True},
    ):
        got = memory_pack.save_memory(_ctx(), args)
        assert got.data["status"] == "rejected"
        assert got.data["reason"]

    assert memory_pack.save_memory(_ctx(), None).data["status"] == "rejected"
    assert _count_memories() == 0

    cite = memory_pack.save_memory(
        _ctx(),
        {
            "kind": "cite",
            "source": "whatever",
            "target": "author-year",
            "confirm": True,
        },
    )
    assert cite.data["status"] == "saved"
    assert cite.data["source"] == "default"
    row = _only_memory()
    assert row["kind"] == "cite"
    assert row["source"] == "default"
    assert row["hits"] == 0
    _clean_memories()
