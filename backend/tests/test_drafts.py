"""起草与引文（契约 §2.6 / N18–N21）的测试。

覆盖三件最容易被写坏的事：

1. ⭐ **`PATCH` 必须能"清空正文"** —— `body_md=""` 与"没传正文"是两回事；
2. ⭐ **引文的 `order`（文内编号）由服务端算** —— 前端自己数会在删除后错位
   （M4 格式检查第一条就查连续性）；
3. ⭐ **归属**：别人的草稿 / 别人的素材一律 404；**软删的素材不许再被引用**。

⚠️ 不用 `tmp_path`（AGENTS.md：受限环境不可写）——
用 `conftest` 那套临时库 + `SessionLocal` 直接建行。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import TEST_USER_ID, create_user_row

from app.db import SessionLocal
from app.main import app
from app.models import Citation, Draft, Material, Task
from app.routers.drafts import build_csl_json
from app.timeutil import utc_now


def _make_material(
    *,
    source_name: str = "chem_arXiv_2609.37896v1.pdf",
    page: int = 2,
    text_quote: str = "the chiral measures are conserved",
    translated_quote: str | None = "手性测度是守恒的",
    task_id: int | None = None,
    block_id: str | None = "p1_b2",
    note: str | None = None,
    deleted: bool = False,
    user_id: int = TEST_USER_ID,
) -> int:
    """直接入库建一张素材卡（素材的**创建接口**不在本卡，属另一张任务卡）。

    ⚠️ 四个"深拷贝"列（`text_quote` / `translated_quote` / `page` / `source_name`）
    是 `materials` 的全部意义，所以这里**照实填**，别用占位串。
    """
    with SessionLocal() as session:
        row = Material(
            user_id=user_id,
            task_id=task_id,
            block_id=block_id,
            text_quote=text_quote,
            translated_quote=translated_quote,
            page=page,
            source_name=source_name,
            note=note,
            created_at=utc_now(),
        )
        if deleted:
            row.deleted_at = utc_now()
        session.add(row)
        session.commit()
        return row.id


def _make_draft(*, title: str = "我的第一篇草稿", user_id: int = TEST_USER_ID) -> int:
    with SessionLocal() as session:
        row = Draft(user_id=user_id, title=title, body_md="", template_id=None)
        session.add(row)
        session.commit()
        return row.id


def _make_task(user_id: int = TEST_USER_ID) -> int:
    with SessionLocal() as session:
        row = Task(user_id=user_id, filename="src.pdf", status="completed")
        session.add(row)
        session.commit()
        return row.id


# ============================================================ N18

def test_create_and_list_drafts() -> None:
    with TestClient(app) as client:
        created = client.post("/api/drafts", json={"title": "综述初稿"})
        listed = client.get("/api/drafts")

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["title"] == "综述初稿"
    assert body["body_md"] == ""
    assert body["template_id"] is None
    assert body["citations"] == []
    # updated_at 必须带时区（时间口径：接口一律输出带时区的 UTC）
    assert body["updated_at"].endswith("+00:00")

    assert listed.status_code == 200
    items = listed.json()["items"]
    assert [item["title"] for item in items] == ["综述初稿"]


def test_create_draft_carries_template_id() -> None:
    """起稿四入口（模板 / 大纲 / 空白 / 上传模板）落到接口上只差这一个字段。"""
    with TestClient(app) as client:
        res = client.post(
            "/api/drafts", json={"title": "按刊模板起稿", "template_id": "jfe-2026"}
        )

    assert res.status_code == 201
    assert res.json()["template_id"] == "jfe-2026"


def test_create_draft_rejects_empty_title() -> None:
    with TestClient(app) as client:
        res = client.post("/api/drafts", json={"title": ""})

    assert res.status_code == 422


# ============================================================ N19

def test_get_draft_returns_its_citations() -> None:
    material_id = _make_material()
    draft_id = _make_draft()
    with TestClient(app) as client:
        client.post(
            f"/api/drafts/{draft_id}/citations", json={"material_id": material_id}
        )
        res = client.get(f"/api/drafts/{draft_id}")

    assert res.status_code == 200
    citations = res.json()["citations"]
    assert len(citations) == 1
    assert citations[0]["material_id"] == material_id
    assert citations[0]["order"] == 1


def test_patch_updates_only_given_fields() -> None:
    draft_id = _make_draft(title="原标题")
    with TestClient(app) as client:
        client.patch(f"/api/drafts/{draft_id}", json={"body_md": "正文第一版"})
        res = client.patch(f"/api/drafts/{draft_id}", json={"title": "改名了"})

    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "改名了"
    # ⭐ 只传 title 时，正文必须原样保留（不能被 None 抹掉）
    assert body["body_md"] == "正文第一版"


def test_patch_can_clear_body() -> None:
    """⭐ 清空正文：`body_md=""` 要真的清掉，不能被"没传"的判据吞掉。"""
    draft_id = _make_draft()
    with TestClient(app) as client:
        client.patch(f"/api/drafts/{draft_id}", json={"body_md": "先写点东西"})
        res = client.patch(f"/api/drafts/{draft_id}", json={"body_md": ""})

    assert res.status_code == 200
    assert res.json()["body_md"] == ""


def test_delete_draft_removes_its_citations() -> None:
    """⚠️ SQLite 外键没开级联：删草稿必须手工删引文，否则留孤儿行。"""
    material_id = _make_material()
    draft_id = _make_draft()
    with TestClient(app) as client:
        client.post(
            f"/api/drafts/{draft_id}/citations", json={"material_id": material_id}
        )
        res = client.delete(f"/api/drafts/{draft_id}")

    assert res.status_code == 200
    with SessionLocal() as session:
        left = session.query(Citation).filter(Citation.draft_id == draft_id).count()
    assert left == 0


# ============================================================ N20 / N21

def test_create_citation_fills_order_and_csl_json() -> None:
    """⭐ 一次插入要同时落三样：文内编号、CSL-JSON、插入锚点。"""
    material_id = _make_material(note="结论性证据")
    draft_id = _make_draft()
    with TestClient(app) as client:
        res = client.post(
            f"/api/drafts/{draft_id}/citations",
            json={
                "material_id": material_id,
                "anchor": {"block_id": "p3_b1", "offset": 42},
            },
        )

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["order"] == 1
    assert body["anchor"] == {"block_id": "p3_b1", "offset": 42}
    csl = body["csl_json"]
    assert csl["type"] == "article-journal"
    assert csl["page"] == "2"
    assert csl["note"] == "结论性证据"
    assert csl["title"] == "chem_arXiv_2609.37896v1.pdf"


def test_citation_order_increments_on_server_side() -> None:
    """⭐ 编号连续性归服务端 —— 前端自己数会在删除后错位（M4 格式检查第一条查这个）。"""
    a = _make_material(block_id="p0_b1")
    b = _make_material(block_id="p0_b2")
    draft_id = _make_draft()
    with TestClient(app) as client:
        first = client.post(
            f"/api/drafts/{draft_id}/citations", json={"material_id": a}
        )
        second = client.post(
            f"/api/drafts/{draft_id}/citations", json={"material_id": b}
        )
        listed = client.get(f"/api/drafts/{draft_id}/citations")

    assert first.json()["order"] == 1
    assert second.json()["order"] == 2
    assert [item["order"] for item in listed.json()["items"]] == [1, 2]


def test_clear_citations() -> None:
    material_id = _make_material()
    draft_id = _make_draft()
    with TestClient(app) as client:
        client.post(
            f"/api/drafts/{draft_id}/citations", json={"material_id": material_id}
        )
        res = client.delete(f"/api/drafts/{draft_id}/citations")
        listed = client.get(f"/api/drafts/{draft_id}/citations")

    assert res.status_code == 200
    assert listed.json()["items"] == []


# ============================================================ 归属与软删

def test_other_users_draft_is_404() -> None:
    other_id = create_user_row("someone-else", "pw12345678")
    mine = _make_draft()
    with SessionLocal() as session:
        theirs = Draft(user_id=other_id, title="别人的稿", body_md="")
        session.add(theirs)
        session.commit()
        theirs_id = theirs.id

    with TestClient(app) as client:
        assert client.get(f"/api/drafts/{theirs_id}").status_code == 404
        assert (
            client.patch(f"/api/drafts/{theirs_id}", json={"title": "x"}).status_code
            == 404
        )
        assert client.delete(f"/api/drafts/{theirs_id}").status_code == 404
        # 自己的那篇照常
        assert client.get(f"/api/drafts/{mine}").status_code == 200


def test_other_users_material_cannot_be_cited() -> None:
    other_id = create_user_row("someone-else-2", "pw12345678")
    theirs_material = _make_material(user_id=other_id)
    draft_id = _make_draft()
    with TestClient(app) as client:
        res = client.post(
            f"/api/drafts/{draft_id}/citations", json={"material_id": theirs_material}
        )

    assert res.status_code == 404


def test_missing_material_is_404() -> None:
    draft_id = _make_draft()
    with TestClient(app) as client:
        res = client.post(
            f"/api/drafts/{draft_id}/citations", json={"material_id": 999999}
        )

    assert res.status_code == 404


def test_soft_deleted_material_cannot_be_cited() -> None:
    """软删（`deleted_at` 非空）的素材不许再插进新稿。"""
    material_id = _make_material(deleted=True)
    draft_id = _make_draft()
    with TestClient(app) as client:
        res = client.post(
            f"/api/drafts/{draft_id}/citations", json={"material_id": material_id}
        )

    assert res.status_code == 404


# ============================================================ CSL-JSON 的诚实性

def test_csl_json_omits_fields_we_do_not_have() -> None:
    """⭐ **不编数据**：素材卡只有四个深拷贝列，所以 `author` / `container-title` /
    `issued` / `DOI` 一律**不写** —— 绝不用"未知作者"这类占位串冒充
    （那会让 M4 拿到假字段）。
    """
    material_id = _make_material()
    with SessionLocal() as session:
        material = session.get(Material, material_id)
        csl = build_csl_json(material)

    for absent in ("author", "container-title", "issued", "DOI"):
        assert absent not in csl, f"{absent} 我们拿不到，不许编"
    # 真有的字段要在
    assert set(csl) >= {"id", "type", "title", "page"}


def test_csl_json_is_stored_at_insert_time() -> None:
    """⭐ `csl_json` 是**插入时**生成的（契约原文），不是查询时现算。
    落库了就查得到。
    """
    material_id = _make_material()
    draft_id = _make_draft()
    with TestClient(app) as client:
        created = client.post(
            f"/api/drafts/{draft_id}/citations", json={"material_id": material_id}
        )
        listed = client.get(f"/api/drafts/{draft_id}/citations")

    assert created.json()["csl_json"] == listed.json()["items"][0]["csl_json"]
    with SessionLocal() as session:
        row = session.query(Citation).filter(Citation.draft_id == draft_id).one()
    assert isinstance(row.csl_json, dict)
    assert row.csl_json["type"] == "article-journal"


def test_source_task_kept_for_jump_back() -> None:
    """引文靠 `material_id` 回跳：素材的 `task_id` / `block_id` 要能带出来
    （供前端回原文高亮）。
    """
    task_id = _make_task()
    material_id = _make_material(task_id=task_id, block_id="p5_b3")
    with SessionLocal() as session:
        material = session.get(Material, material_id)
    assert material.task_id == task_id
    assert material.block_id == "p5_b3"
