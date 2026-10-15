"""知识库 · 集合（契约 §2.1 / N1–N5）的测试。

盯五件事：

1. ⭐ **两个计数**：`doc_count` 只数**直接成员**，`doc_count_deep` 才是含子集合
   的聚合数——这条要造"父 - 子 - 文献挂在子"三行数据才证得出来；
2. ⭐ **成环由服务端挡**（400），不许只靠前端；
3. **同一父下不许重名**（400），不同父下可以同名；改名 / 移动**也要**查重
   （不查就撞唯一约束，从 400 变 500）；
4. **删集合只删集合**：子集合回到父级、文献还在（只是脱离这个集合）；
5. **归属**：别人的集合、别人的文献一律 404。

⚠️ 不用 `tmp_path`（AGENTS.md：受限环境不可写）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import TEST_USER_ID, create_user_row

from app.db import SessionLocal
from app.main import app
from app.models import Collection, Task, TaskCollection
from app.timeutil import utc_now

client = TestClient(app)


def _task(
    *,
    user_id: int = TEST_USER_ID,
    reading_status: str = "todo",
    archived: bool = False,
) -> int:
    with SessionLocal() as session:
        row = Task(
            user_id=user_id,
            filename="p.pdf",
            status="completed",
            reading_status=reading_status,
        )
        if archived:
            row.archived_at = utc_now()
        session.add(row)
        session.commit()
        return row.id


def _link(task_id: int, collection_id: int) -> None:
    with SessionLocal() as session:
        session.add(TaskCollection(task_id=task_id, collection_id=collection_id))
        session.commit()


def _collection(
    name: str, parent_id: int | None = None, *, user_id: int = TEST_USER_ID
) -> int:
    with SessionLocal() as session:
        row = Collection(user_id=user_id, name=name, parent_id=parent_id)
        session.add(row)
        session.commit()
        return row.id


def _items() -> dict[str, dict]:
    response = client.get("/api/collections")
    assert response.status_code == 200
    return {row["name"]: row for row in response.json()["items"]}


# ============================================================ N1 / N5：计数

def test_counts_only_direct_members_but_deep_includes_children():
    """⭐ 父-子-文献挂在子：父 `doc_count` 必须是 0，`doc_count_deep` 才是 1。"""
    parent = client.post("/api/collections", json={"name": "甲"}).json()
    child = client.post(
        "/api/collections", json={"name": "乙", "parent_id": parent["id"]}
    ).json()
    task_id = _task()
    response = client.put(
        f"/api/tasks/{task_id}/collections", json={"collection_ids": [child["id"]]}
    )
    assert response.status_code == 200
    assert response.json() == {"collection_ids": [child["id"]]}

    items = _items()
    assert items["乙"]["doc_count"] == 1
    assert items["乙"]["doc_count_deep"] == 1
    assert items["甲"]["doc_count"] == 0  # ⭐ 子集合的文献不算在父集合里
    assert items["甲"]["doc_count_deep"] == 1  # 括号辅数
    assert items["甲"]["parent_id"] is None
    assert items["乙"]["parent_id"] == parent["id"]


def test_archived_documents_are_not_counted():
    """列表里藏起来的文献不该算进"N 篇"（否则界面说 2 篇、点进去只有 1 篇）。"""
    collection = _collection("甲")
    _link(_task(), collection)
    _link(_task(archived=True), collection)
    assert _items()["甲"]["doc_count"] == 1


def test_n5_replaces_dedupes_and_rejects_unknown_ids():
    first = client.post("/api/collections", json={"name": "甲"}).json()["id"]
    second = client.post("/api/collections", json={"name": "乙"}).json()["id"]
    task_id = _task()

    response = client.put(
        f"/api/tasks/{task_id}/collections",
        json={"collection_ids": [first, second, first]},
    )
    assert response.json() == {"collection_ids": [first, second]}

    # 全量替换：只给一个，另一个就脱离
    response = client.put(
        f"/api/tasks/{task_id}/collections", json={"collection_ids": [second]}
    )
    assert response.json() == {"collection_ids": [second]}
    items = _items()
    assert items["甲"]["doc_count"] == 0
    assert items["乙"]["doc_count"] == 1

    response = client.put(
        f"/api/tasks/{task_id}/collections", json={"collection_ids": [9999]}
    )
    assert response.status_code == 400
    assert "集合不存在" in response.json()["detail"]


# ============================================================ N2 / N3：重名与成环

def test_same_parent_duplicate_is_400_but_other_parent_is_ok():
    parent = client.post("/api/collections", json={"name": "甲"}).json()["id"]
    assert client.post("/api/collections", json={"name": "同名"}).status_code == 201
    assert client.post("/api/collections", json={"name": "同名"}).status_code == 400

    # 不同父下可以同名
    response = client.post(
        "/api/collections", json={"name": "同名", "parent_id": parent}
    )
    assert response.status_code == 201


def test_parent_must_exist_and_name_must_be_valid():
    response = client.post("/api/collections", json={"name": "甲", "parent_id": 9999})
    assert response.status_code == 400
    assert client.post("/api/collections", json={"name": "  "}).status_code == 400
    assert client.post("/api/collections", json={"name": "x" * 65}).status_code == 400


def test_patch_renames_moves_and_sorts():
    parent = client.post("/api/collections", json={"name": "甲"}).json()["id"]
    child = client.post("/api/collections", json={"name": "乙"}).json()["id"]

    response = client.patch(
        f"/api/collections/{child}",
        json={"name": "丙", "parent_id": parent, "sort": 7},
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["name"], body["parent_id"], body["sort"]) == ("丙", parent, 7)

    # 传 null = 移回顶层（"没传"与"传了 null"是两件事）
    response = client.patch(f"/api/collections/{child}", json={"parent_id": None})
    assert response.json()["parent_id"] is None


def test_moving_into_own_descendant_is_400():
    """⭐ 成环：不许把自己移进自己的后代（含移进自己）。"""
    parent = client.post("/api/collections", json={"name": "甲"}).json()["id"]
    child = client.post(
        "/api/collections", json={"name": "乙", "parent_id": parent}
    ).json()["id"]
    grand = client.post(
        "/api/collections", json={"name": "丙", "parent_id": child}
    ).json()["id"]

    for bad_parent in (parent, child, grand):
        response = client.patch(
            f"/api/collections/{parent}", json={"parent_id": bad_parent}
        )
        assert response.status_code == 400, bad_parent
        assert "后代" in response.json()["detail"]


def test_rename_into_existing_sibling_is_400():
    """改名撞同一个父下的重名也要挡（不挡会撞唯一约束变成 500）。"""
    client.post("/api/collections", json={"name": "甲"})
    second = client.post("/api/collections", json={"name": "乙"}).json()["id"]
    response = client.patch(f"/api/collections/{second}", json={"name": "甲"})
    assert response.status_code == 400
    assert "重名" in response.json()["detail"]


# ============================================================ N4：只删集合

def test_delete_only_removes_the_collection():
    """子集合回到被删集合的父级；文献不被删，只是脱离这个集合。"""
    root = client.post("/api/collections", json={"name": "根"}).json()["id"]
    middle = client.post(
        "/api/collections", json={"name": "中", "parent_id": root}
    ).json()["id"]
    leaf = client.post(
        "/api/collections", json={"name": "叶", "parent_id": middle}
    ).json()["id"]
    task_id = _task()
    _link(task_id, middle)

    response = client.delete(f"/api/collections/{middle}")
    assert response.status_code == 200
    # 1 个子集合 + 1 篇直接文献
    assert response.json() == {"deleted": True, "moved_to_parent": 2}

    items = _items()
    assert "中" not in items
    assert items["叶"]["id"] == leaf  # 子集合还在（只是换了父）
    assert items["叶"]["parent_id"] == root
    with SessionLocal() as session:
        assert session.get(Task, task_id) is not None  # 文献还在
        links = session.query(TaskCollection).filter_by(collection_id=middle).all()
        assert links == []  # 只是脱离了被删的集合
    assert items["叶"]["doc_count"] == 0


def test_delete_unknown_is_404():
    assert client.delete("/api/collections/9999").status_code == 404


# ============================================================ 归属

def test_others_data_is_404():
    other = create_user_row("other-collections", "pw-other")
    theirs = _collection("别人的", user_id=other)
    task_id = _task()
    their_task = _task(user_id=other)

    assert client.get("/api/collections").json()["items"] == []
    response = client.patch(f"/api/collections/{theirs}", json={"name": "改"})
    assert response.status_code == 404
    assert client.delete(f"/api/collections/{theirs}").status_code == 404
    # 别人的 task 进不去
    assert (
        client.put(
            f"/api/tasks/{their_task}/collections", json={"collection_ids": []}
        ).status_code
        == 404
    )
    # 别人的集合 id 当成自己的用 → 400（与"不存在"同一句，不暴露存在性）
    response = client.put(
        f"/api/tasks/{task_id}/collections", json={"collection_ids": [theirs]}
    )
    assert response.status_code == 400
    assert "集合不存在" in response.json()["detail"]
