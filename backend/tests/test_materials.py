"""素材卡（契约 §2.4 / N12–N14）的测试。

⭐ 这一包盯的就是 **M2 的验收判据**（`docs/任务划分与分工_v1_20261014.md`）：

1. ⭐⭐ **建一张卡 → 删掉源任务 → `GET /api/materials` 里那张卡仍显示
   `source_name` / `page` / `text_quote`**，且 `task_id` 变 null、**卡不级联删**；
2. 软删（`deleted_at`）后列表不再返回，重复删**幂等**；
3. **非本人一律 404**；
4. 页码从块编号推导（`p{0 起}_b{n}` → 人读 +1）；**推不出就 400，绝不编页码**；
5. 列表的 `?task_id?` `&collection_id?` `&tag?` 三个筛选（集合/标签挂在**源文献**上）。

⚠️ 不用 `tmp_path`（AGENTS.md：受限环境不可写）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import TEST_USER_ID, create_user_row

from app.db import SessionLocal
from app.main import app
from app.models import (
    Collection,
    Material,
    Tag,
    Task,
    TaskBlock,
    TaskCollection,
    TaskTag,
)
from app.timeutil import utc_now

# 前端契约 mock 的 `materialView` 就是这批字段（两边不许各写一套）
WIRE_KEYS = {
    "id",
    "text_quote",
    "translated_quote",
    "page",
    "source_name",
    "note",
    "task_id",
    "block_id",
    "deleted_at",
    "created_at",
}


def _make_task(*, user_id: int = TEST_USER_ID, filename: str = "chem_arXiv.pdf") -> int:
    with SessionLocal() as session:
        row = Task(user_id=user_id, filename=filename, status="completed")
        session.add(row)
        session.commit()
        return row.id


def _make_block(
    *,
    task_id: int,
    block_id: str = "p0_b1",
    text: str = "the chiral measures are conserved",
    translated: str | None = "手性测度是守恒的",
) -> None:
    with SessionLocal() as session:
        session.add(
            TaskBlock(
                task_id=task_id,
                block_id=block_id,
                text=text,
                translated=translated,
            )
        )
        session.commit()


def _create(client: TestClient, task_id: int, block_id: str = "p0_b1", **extra):
    return client.post(
        "/api/materials",
        json={"task_id": task_id, "block_id": block_id, **extra},
    )


# ============================================================ N12


def test_create_material_deep_copies_provenance() -> None:
    """快照的四个字段**创建时深拷贝**（这是整张表的全部意义）。"""
    task_id = _make_task(filename="chem_arXiv_2609.37896v1.pdf")
    _make_block(task_id=task_id, block_id="p0_b1")

    with TestClient(app) as client:
        resp = _create(client, task_id, note="这段能当引文用")

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body.keys() == WIRE_KEYS  # 与前端 mock 的形状逐字段对齐
    assert body["text_quote"] == "the chiral measures are conserved"
    assert body["translated_quote"] == "手性测度是守恒的"
    assert body["source_name"] == "chem_arXiv_2609.37896v1.pdf"
    assert body["page"] == 1  # `p0` → 人读第 1 页
    assert body["note"] == "这段能当引文用"
    assert body["task_id"] == task_id
    assert body["block_id"] == "p0_b1"
    assert body["deleted_at"] is None
    assert body["created_at"].endswith("+00:00")  # 时间一律带时区


def test_m2_judgement_card_survives_source_task_deletion() -> None:
    """⭐⭐ **M2 的判据本体**：删掉源任务，素材卡仍显示出处，`task_id` 变 null。"""
    task_id = _make_task(filename="chem_arXiv.pdf")
    _make_block(task_id=task_id, block_id="p2_b7")

    with TestClient(app) as client:
        created = _create(client, task_id, "p2_b7")
        assert created.status_code == 201, created.text
        material_id = created.json()["id"]

        deleted = client.delete(f"/api/tasks/{task_id}")
        assert deleted.status_code == 200, deleted.text

        listed = client.get("/api/materials")

    assert listed.status_code == 200
    rows = [row for row in listed.json()["items"] if row["id"] == material_id]
    assert len(rows) == 1, "源任务被删后素材卡必须还在（不许级联删）"
    card = rows[0]
    assert card["source_name"] == "chem_arXiv.pdf"  # 快照，不是 JOIN 出来的
    assert card["page"] == 3  # `p2` → 第 3 页
    assert card["text_quote"] == "the chiral measures are conserved"
    assert card["task_id"] is None, "源文献已删：task_id 要脱开，界面据此说「仅存快照」"


def test_create_material_404_when_block_or_task_is_not_ours() -> None:
    """块不存在、以及**别人的任务**，都回同一句 404（不暴露"存在但无权限"）。"""
    mine = _make_task(filename="mine.pdf")
    _make_block(task_id=mine, block_id="p0_b1")

    other_id = create_user_row("other-user", "pw-12345678")
    theirs = _make_task(user_id=other_id, filename="theirs.pdf")
    _make_block(task_id=theirs, block_id="p0_b1")

    with TestClient(app) as client:
        missing_block = _create(client, mine, "p9_b9")
        theirs_task = _create(client, theirs, "p0_b1")
        unknown_task = _create(client, 999_999, "p0_b1")

    assert missing_block.status_code == 404
    assert theirs_task.status_code == 404
    assert unknown_task.status_code == 404


def test_page_not_derivable_is_400_and_creates_nothing() -> None:
    """编号里推不出页码时**拒绝**（`page` 是必填，编一个会印到出处芯片上）。"""
    task_id = _make_task()
    _make_block(task_id=task_id, block_id="scan-block-7")

    with TestClient(app) as client:
        resp = _create(client, task_id, "scan-block-7")

    assert resp.status_code == 400
    with SessionLocal() as session:
        assert session.query(Material).count() == 0


# ============================================================ N13


def test_list_filters_by_task_collection_and_tag() -> None:
    """`?task_id?` `&collection_id?` `&tag?`（集合与标签挂在**源文献**上）。"""
    task_a = _make_task(filename="a.pdf")
    task_b = _make_task(filename="b.pdf")
    _make_block(task_id=task_a, block_id="p0_b1")
    _make_block(task_id=task_b, block_id="p0_b1")

    with SessionLocal() as session:
        collection = Collection(user_id=TEST_USER_ID, name="手性专题")
        tag = Tag(user_id=TEST_USER_ID, name="手性", kind="topic")
        session.add_all([collection, tag])
        session.commit()
        session.add_all(
            [
                TaskCollection(task_id=task_a, collection_id=collection.id),
                TaskTag(task_id=task_a, tag_id=tag.id),
            ]
        )
        session.commit()
        collection_id = collection.id

    with TestClient(app) as client:
        a_id = _create(client, task_a).json()["id"]
        b_id = _create(client, task_b).json()["id"]

        by_task = client.get("/api/materials", params={"task_id": task_b})
        by_collection = client.get(
            "/api/materials", params={"collection_id": collection_id}
        )
        by_tag = client.get("/api/materials", params={"tag": "手性"})
        all_rows = client.get("/api/materials")

    assert [row["id"] for row in by_task.json()["items"]] == [b_id]
    assert [row["id"] for row in by_collection.json()["items"]] == [a_id]
    assert [row["id"] for row in by_tag.json()["items"]] == [a_id]
    assert {row["id"] for row in all_rows.json()["items"]} == {a_id, b_id}


def test_list_only_returns_my_own_and_hides_soft_deleted() -> None:
    other_id = create_user_row("other-user", "pw-12345678")
    theirs = _make_task(user_id=other_id, filename="theirs.pdf")
    _make_block(task_id=theirs, block_id="p0_b1")
    with SessionLocal() as session:
        session.add(
            Material(
                user_id=other_id,
                task_id=theirs,
                block_id="p0_b1",
                text_quote="别人的原文",
                translated_quote=None,
                page=1,
                source_name="theirs.pdf",
                created_at=utc_now(),
            )
        )
        session.commit()

    mine = _make_task(filename="mine.pdf")
    _make_block(task_id=mine, block_id="p0_b2")
    with TestClient(app) as client:
        kept = _create(client, mine, "p0_b2").json()["id"]
        gone = _create(client, mine, "p0_b2").json()["id"]
        assert client.delete(f"/api/materials/{gone}").status_code == 200

        listed = client.get("/api/materials")

    assert [row["id"] for row in listed.json()["items"]] == [kept]


# ============================================================ N14


def test_soft_delete_is_idempotent_and_keeps_the_row() -> None:
    """只写 `deleted_at`（§7.7 撤销窗口）；再删一次仍 200，行**不被真删**。"""
    task_id = _make_task()
    _make_block(task_id=task_id, block_id="p0_b1")

    with TestClient(app) as client:
        material_id = _create(client, task_id).json()["id"]
        first = client.delete(f"/api/materials/{material_id}")
        second = client.delete(f"/api/materials/{material_id}")

    assert first.status_code == 200, first.text
    assert first.json()["deleted_at"].endswith("+00:00")
    assert second.status_code == 200
    assert second.json()["deleted_at"] == first.json()["deleted_at"]
    with SessionLocal() as session:
        row = session.get(Material, material_id)
        assert row is not None and row.deleted_at is not None


def test_delete_others_material_is_404() -> None:
    other_id = create_user_row("other-user", "pw-12345678")
    other_task = _make_task(user_id=other_id, filename="theirs.pdf")
    _make_block(task_id=other_task, block_id="p0_b1")
    with SessionLocal() as session:
        row = Material(
            user_id=other_id,
            task_id=other_task,
            block_id="p0_b1",
            text_quote="别人的原文",
            translated_quote=None,
            page=1,
            source_name="theirs.pdf",
            created_at=utc_now(),
        )
        session.add(row)
        session.commit()
        material_id = row.id

    with TestClient(app) as client:
        resp = client.delete(f"/api/materials/{material_id}")

    assert resp.status_code == 404
    with SessionLocal() as session:
        assert session.get(Material, material_id).deleted_at is None
