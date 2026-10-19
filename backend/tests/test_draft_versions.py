"""草稿版本历史（2026-10-19）的测试。

钉五件事（每条都对应一个会真出事的口径）：

1. `PATCH` 保存正文后**自动记一版**，且版本里就是存下去的那份正文；
2. **内容没变不重复记** —— 同一秒里连点保存会攒出一串空壳版本，把 50 版额度吃光；
3. `restore` 能回滚，且**中间稿被存成 `source="restore"` 的一版**（回滚本身可撤销）；
4. **归属**：别人的草稿在列表 / 详情 / restore 三个端点都 404；
5. **上限 50 版**是硬规则：第 52 版进来时最旧的两版必须真的被删。

⚠️ 不用 `tmp_path`（AGENTS.md：受限环境不可写）——
用 `conftest` 那套临时库 + `SessionLocal` 直接建行。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import TEST_USER_ID, create_user_row
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import Draft, DraftVersion


def _make_draft(
    *, title: str = "我的草稿", body_md: str = "", user_id: int = TEST_USER_ID
) -> int:
    with SessionLocal() as session:
        row = Draft(user_id=user_id, title=title, body_md=body_md, template_id=None)
        session.add(row)
        session.commit()
        return row.id


def _versions_of(draft_id: int) -> list[tuple[int, str, str]]:
    """`(id, source, body_md)`，按 `id` 升序（= 真实先后，不受同秒影响）。"""
    with SessionLocal() as session:
        rows = session.execute(
            select(DraftVersion.id, DraftVersion.source, DraftVersion.body_md)
            .where(DraftVersion.draft_id == draft_id)
            .order_by(DraftVersion.id)
        ).all()
    return [(row[0], row[1], row[2]) for row in rows]


# ============================================================ ① 保存即记一版

def test_patch_records_the_saved_body() -> None:
    draft_id = _make_draft()
    with TestClient(app) as client:
        saved = client.patch(f"/api/drafts/{draft_id}", json={"body_md": "# 第一版"})
        listed = client.get(f"/api/drafts/{draft_id}/versions")

        assert saved.status_code == 200
        assert listed.status_code == 200
        items = listed.json()["items"]
        assert len(items) == 1
        assert items[0]["source"] == "user"
        assert items[0]["note"] is None
        assert items[0]["chars"] == len("# 第一版")
        # 时间口径：接口一律输出带时区的 UTC
        assert items[0]["created_at"].endswith("+00:00")
        # 列表是**轻量**的：不返回正文
        assert "body_md" not in items[0]

        detail = client.get(f"/api/drafts/{draft_id}/versions/{items[0]['id']}")

    assert detail.status_code == 200
    body = detail.json()
    assert body["body_md"] == "# 第一版"
    assert body["title"] == "我的草稿"
    assert body["source"] == "user"
    assert body["created_at"].endswith("+00:00")

    versions = _versions_of(draft_id)
    assert [(source, text) for _, source, text in versions] == [("user", "# 第一版")]


# ============================================================ ② 幂等

def test_unchanged_body_is_not_recorded_again() -> None:
    """同一份正文连点保存、或只改标题，都不许长版本。"""
    draft_id = _make_draft()
    with TestClient(app) as client:
        for _ in range(3):
            res = client.patch(
                f"/api/drafts/{draft_id}", json={"body_md": "同一份正文"}
            )
            assert res.status_code == 200
        # 只改标题：正文没变 → 也不该记
        client.patch(f"/api/drafts/{draft_id}", json={"title": "改个名字"})
        listed = client.get(f"/api/drafts/{draft_id}/versions")

    assert len(listed.json()["items"]) == 1
    assert len(_versions_of(draft_id)) == 1


# ============================================================ ③ 回滚 + 留痕

def test_restore_rolls_back_and_snapshots_the_intermediate_body() -> None:
    draft_id = _make_draft()
    with TestClient(app) as client:
        client.patch(f"/api/drafts/{draft_id}", json={"body_md": "AI 动手之前"})
        before = client.get(f"/api/drafts/{draft_id}/versions").json()["items"][0]
        client.patch(f"/api/drafts/{draft_id}", json={"body_md": "AI 改写之后"})
        assert len(client.get(f"/api/drafts/{draft_id}/versions").json()["items"]) == 2

        # ⭐ 详情只读回显：看完不该改稿
        peek = client.get(f"/api/drafts/{draft_id}/versions/{before['id']}")
        still = client.get(f"/api/drafts/{draft_id}")

        restored = client.post(
            f"/api/drafts/{draft_id}/versions/{before['id']}/restore"
        )
        listed = client.get(f"/api/drafts/{draft_id}/versions")

    assert peek.status_code == 200
    assert peek.json()["body_md"] == "AI 动手之前"
    assert still.json()["body_md"] == "AI 改写之后"

    assert restored.status_code == 200
    # 形状照 `_serialize_draft`（前端直接复用同一份渲染）
    assert restored.json()["body_md"] == "AI 动手之前"
    assert restored.json()["citations"] == []
    # 只写回正文，不擅自改标题
    assert restored.json()["title"] == "我的草稿"

    items = listed.json()["items"]
    # 2 版 + 回滚前的快照
    assert len(items) == 3
    assert items[0]["source"] == "restore"
    # ⭐ 中间稿真的被存下来了（"回滚把中间稿弄丢"就出在这里）
    assert items[0]["chars"] == len("AI 改写之后")
    assert _versions_of(draft_id)[-1][2] == "AI 改写之后"


# ============================================================ ④ 归属

def test_other_users_versions_are_404() -> None:
    other_id = create_user_row("someone-else", "pw12345678")
    theirs = _make_draft(user_id=other_id, title="别人的稿", body_md="别人的正文")
    with SessionLocal() as session:
        row = DraftVersion(
            draft_id=theirs,
            body_md="别人的正文",
            title="别人的稿",
            source="user",
        )
        session.add(row)
        session.commit()
        version_id = row.id

    with TestClient(app) as client:
        assert client.get(f"/api/drafts/{theirs}/versions").status_code == 404
        detail_url = f"/api/drafts/{theirs}/versions/{version_id}"
        assert client.get(detail_url).status_code == 404
        assert client.post(f"{detail_url}/restore").status_code == 404

    # 别人的版本一行都没被动（没被回滚、也没被删）
    assert len(_versions_of(theirs)) == 1


def test_version_of_another_draft_is_404() -> None:
    """自己的两篇稿之间也不许串：拿 A 的版本 id 去 B 上取 → 404。"""
    mine = _make_draft(title="我的稿")
    other = _make_draft(title="我的另一篇稿")
    with TestClient(app) as client:
        client.patch(f"/api/drafts/{mine}", json={"body_md": "别处的正文"})
        foreign = client.get(f"/api/drafts/{mine}/versions").json()["items"][0]
        res = client.get(f"/api/drafts/{other}/versions/{foreign['id']}")

    assert res.status_code == 404


# ============================================================ ⑤ 50 版上限

def test_old_versions_are_trimmed_to_the_latest_fifty() -> None:
    draft_id = _make_draft()
    with TestClient(app) as client:
        for index in range(52):
            res = client.patch(
                f"/api/drafts/{draft_id}", json={"body_md": f"第 {index} 版"}
            )
            assert res.status_code == 200
        listed = client.get(f"/api/drafts/{draft_id}/versions?limit=100")

    items = listed.json()["items"]
    assert len(items) == 50

    bodies = [text for _, _, text in _versions_of(draft_id)]
    assert len(bodies) == 50
    # 砍掉的是**最旧**的两版，最新的一版必须还在
    assert "第 0 版" not in bodies
    assert "第 1 版" not in bodies
    assert bodies[0] == "第 2 版"
    assert bodies[-1] == "第 51 版"
