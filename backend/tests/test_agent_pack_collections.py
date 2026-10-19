"""集合工具包的行为（2026-10-19）。

为什么值得单独测：这三个工具**会改用户的知识库**（建集合、改归属）。
判据必须钉死：只动自己的、重名不重复建、N5 全量替换由工具替调用方算好、失败要说人话。
"""

from __future__ import annotations

from helpers import TEST_USER_ID

from app.agent.contracts import ToolContext
from app.agent.packs.collections import (
    PACK,
    assign_task,
    create_collection,
    list_collections,
)
from app.db import SessionLocal
from app.models import Collection, Task, TaskCollection


def _ctx() -> ToolContext:
    return ToolContext(db=None, user_id=TEST_USER_ID, scene_id="read_ask", scope={})


def _task(filename: str = "集合测试.pdf") -> int:
    with SessionLocal() as session:
        row = Task(user_id=TEST_USER_ID, filename=filename, status="completed")
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def _collection(name: str, parent_id: int | None = None) -> int:
    with SessionLocal() as session:
        row = Collection(user_id=TEST_USER_ID, name=name, parent_id=parent_id, sort=0)
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def test_pack_exposes_three_tools() -> None:
    assert PACK.name == "collections"
    assert [spec.name for spec in PACK.tools] == [
        "list_collections",
        "create_collection",
        "assign_task",
    ]


def test_list_returns_own_collections_with_direct_count() -> None:
    coll = _collection("数学")
    task_id = _task("列表计数.pdf")
    with SessionLocal() as session:
        session.add(TaskCollection(task_id=task_id, collection_id=coll))
        session.commit()

    result = list_collections(_ctx())
    hit = next(item for item in result.data if item["id"] == coll)
    assert hit["name"] == "数学"
    # ⚠️ 只数直接成员（子集合的不算），与 N1 同一条语义
    assert hit["doc_count"] == 1


def test_create_is_idempotent_on_same_name() -> None:
    first = create_collection(_ctx(), {"name": "毕业论文"})
    assert first.data["name"] == "毕业论文"

    second = create_collection(_ctx(), {"name": "毕业论文"})
    assert second.data["existing_id"] == first.data["id"]
    assert "已经有" in second.note

    with SessionLocal() as session:
        same = session.query(Collection).filter(Collection.name == "毕业论文").all()
    assert len(same) == 1, "重名不该建出两条"


def test_create_rejects_missing_parent() -> None:
    result = create_collection(_ctx(), {"name": "子集合", "parent_id": 999999})
    assert result.data == {}
    assert "父集合不存在" in result.note


def test_create_rejects_empty_name() -> None:
    assert "名字" in create_collection(_ctx(), {"name": "  "}).note


def test_assign_add_keeps_existing_memberships() -> None:
    """N5 是全量替换，但 add 模式必须**保留**原有的其它集合。"""
    a = _collection("A 组")
    b = _collection("B 组")
    task_id = _task("归类.pdf")
    with SessionLocal() as session:
        session.add(TaskCollection(task_id=task_id, collection_id=a))
        session.commit()

    result = assign_task(
        _ctx(), {"task_id": task_id, "collection": "B 组", "mode": "add"}
    )
    assert sorted(result.data["collection_ids"]) == sorted([a, b])

    with SessionLocal() as session:
        ids = {
            row.collection_id
            for row in session.query(TaskCollection)
            .filter(TaskCollection.task_id == task_id)
            .all()
        }
    assert ids == {a, b}


def test_assign_remove_leaves_others() -> None:
    a = _collection("要移出")
    b = _collection("要留下")
    task_id = _task("移出.pdf")
    with SessionLocal() as session:
        session.add_all(
            [
                TaskCollection(task_id=task_id, collection_id=a),
                TaskCollection(task_id=task_id, collection_id=b),
            ]
        )
        session.commit()

    result = assign_task(_ctx(), {
        "task_id": task_id, "collection": str(a), "mode": "remove"
    })
    assert result.data["collection_ids"] == [b]


def test_assign_by_name_is_case_insensitive() -> None:
    coll = _collection("Chirality")
    task_id = _task("大小写.pdf")
    result = assign_task(
        _ctx(), {"task_id": task_id, "collection": " chirality ", "mode": "add"}
    )
    assert result.data["collection_ids"] == [coll]


def test_assign_unknown_collection_does_not_touch_data() -> None:
    task_id = _task("不乱写.pdf")
    result = assign_task(_ctx(), {"task_id": task_id, "collection": "不存在的集合"})
    assert result.data == {}
    assert "没有这个集合" in result.note
    with SessionLocal() as session:
        assert session.query(TaskCollection).filter(
            TaskCollection.task_id == task_id
        ).count() == 0


def test_assign_other_users_task_is_not_found() -> None:
    """别人的文献当"找不到"（不暴露存在性），且不改任何归属。"""
    other = _task("别人的.pdf")
    with SessionLocal() as session:
        row = session.get(Task, other)
        row.user_id = TEST_USER_ID + 1
        session.commit()

    result = assign_task(
        _ctx(), {"task_id": other, "collection": "数学", "mode": "add"}
    )
    assert "不在你的库里" in result.note
