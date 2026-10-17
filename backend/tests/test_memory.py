"""记忆（M7）的测试：跨文献用法偏好的 CRUD 与请求前注入。

盯七件事（每一条都对应一个"真会发生"的错法）：

1. ⭐ **一条都没有时如实空**（列表回 `[]`、counts 全 0）——**不许编**；
2. ⭐ **按 `(user, kind, source)` 幂等**：同一个人同一个词再存一次是**改**，不堆第二行
   （否则"同一句话两个说法"当场自相矛盾）；
3. ⭐ **改说法不许把 `hits` 清零**——那是"这条真被用过几次"的账，不是这条记录的年龄；
4. ⭐ **`resolve` 只回启用的**，并且**取过就 `hits += 1`**；
5. ⭐ **别人的记忆一律 404**（不暴露"存在但无权限"，与全站口径一致）；
6. ⭐ **能停用、能真删**（形态 §六"可看可删"；记忆不是留痕，用户说删就得真删）；
7. ⭐ **`cite` 只认一条**：source 一律归一成 `default`，不会堆出两条引用习惯。

⚠️ 不用 `tmp_path`（AGENTS.md：受限环境不可写）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import TEST_USER_ID, create_user_row
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import MemoryItem, User

client = TestClient(app)


def _rows() -> list[MemoryItem]:
    with SessionLocal() as session:
        rows = list(session.scalars(select(MemoryItem).order_by(MemoryItem.id)).all())
        for row in rows:
            session.expunge(row)
    return rows


def _post(**body):
    return client.post("/api/memories", json=body)


def test_空的时候如实回空():
    """⭐ 一条都没有时不许编：列表空、counts 全 0。"""
    res = client.get("/api/memories")
    assert res.status_code == 200
    data = res.json()
    assert data["items"] == []
    assert data["counts"] == {"term": 0, "cite": 0}
    assert data["enabled_counts"] == {"term": 0, "cite": 0}


def test_存一条术语偏好():
    res = _post(kind="term", source="chiral", target="手性")
    assert res.status_code == 201
    data = res.json()
    assert data["created"] is True
    item = data["item"]
    assert item["kind"] == "term"
    assert item["source"] == "chiral"
    assert item["target"] == "手性"
    assert item["hits"] == 0
    assert item["enabled"] is True
    # 时间戳带时区（全站口径，前端按本地解析才不偏）
    assert item["created_at"].endswith("+00:00")

    listed = client.get("/api/memories").json()
    assert len(listed["items"]) == 1
    assert listed["counts"]["term"] == 1


def test_同一个词再存一次是改不是堆():
    """⭐ 幂等判据：同一 (user, kind, source) 只该有一行。"""
    _post(kind="term", source="chiral", target="手性")
    res = _post(kind="term", source="chiral", target="手征性")
    assert res.status_code == 201
    assert res.json()["created"] is False
    assert res.json()["item"]["target"] == "手征性"
    rows = _rows()
    assert len(rows) == 1
    assert rows[0].target == "手征性"


def test_改说法不清零命中数():
    """⭐ `hits` 是"这条真被用上过几次"的账，改说法不该把它抹掉。"""
    client.post(
        "/api/memories", json={"kind": "term", "source": "chiral", "target": "手性"}
    )
    client.get("/api/memories/resolve")  # 让它被"用过"一次
    assert client.get("/api/memories").json()["items"][0]["hits"] == 1

    res = _post(kind="term", source="chiral", target="手征")
    assert res.json()["item"]["hits"] == 1, "改说法把命中数清零了"


def test_空source与空target都挡掉():
    assert (
        _post(kind="term", source="", target="手性").status_code == 422
    )  # 连字段校验都过不了
    assert (
        _post(kind="term", source="   ", target="手性").status_code == 400
    )  # 空白串要单独挡
    assert _post(kind="term", source="chiral", target="   ").status_code == 400
    assert _post(kind="乱写", source="chiral", target="手性").status_code == 400
    assert _rows() == []


def test_引用习惯只认一条():
    """⭐ `cite` 的 source 一律归一成 `default`，不会堆出两条引用习惯。"""
    assert _post(kind="cite", source="随便写", target="author-year").status_code == 201
    assert _post(kind="cite", source="另一个串", target="numeric").status_code == 201
    rows = [r for r in _rows() if r.kind == "cite"]
    assert len(rows) == 1
    assert rows[0].source == "default"
    assert rows[0].target == "numeric"


def test_resolve_只回启用的并计数():
    client.post(
        "/api/memories", json={"kind": "term", "source": "chiral", "target": "手性"}
    )
    client.post(
        "/api/memories", json={"kind": "term", "source": "achiral", "target": "非手性"}
    )
    client.post(
        "/api/memories",
        json={
            "kind": "term",
            "source": "停用的",
            "target": "不该出现",
            "enabled": False,
        },
    )
    client.post(
        "/api/memories",
        json={"kind": "cite", "source": "default", "target": "author-year"},
    )

    data = client.get("/api/memories/resolve").json()
    assert data["terms"] == {"chiral": "手性", "achiral": "非手性"}
    assert data["cite"] == "author-year"
    assert data["counts"] == {"term": 2, "cite": 1}
    # 取过的都 +1，停用的那条不动
    by_source = {r.source: r.hits for r in _rows()}
    assert by_source["chiral"] == 1
    assert by_source["achiral"] == 1
    assert by_source["停用的"] == 0


def test_resolve_两次累加():
    client.post(
        "/api/memories", json={"kind": "term", "source": "chiral", "target": "手性"}
    )
    client.get("/api/memories/resolve")
    client.get("/api/memories/resolve")
    assert client.get("/api/memories").json()["items"][0]["hits"] == 2


def test_改与停用():
    item_id = _post(kind="term", source="chiral", target="手性").json()["item"]["id"]

    res = client.patch(f"/api/memories/{item_id}", json={"target": "手征性"})
    assert res.status_code == 200
    assert res.json()["item"]["target"] == "手征性"

    res = client.patch(f"/api/memories/{item_id}", json={"enabled": False})
    assert res.status_code == 200
    assert res.json()["item"]["enabled"] is False
    # 停用之后不再注入，但仍然看得见（"先别用，但别丢"）
    assert client.get("/api/memories/resolve").json()["terms"] == {}
    assert len(client.get("/api/memories").json()["items"]) == 1
    # 只看启用的：一条都不该有
    assert client.get("/api/memories?enabled=true").json()["items"] == []
    assert len(client.get("/api/memories?enabled=false").json()["items"]) == 1


def test_什么都不给就改是400():
    item_id = _post(kind="term", source="chiral", target="手性").json()["item"]["id"]
    res = client.patch(f"/api/memories/{item_id}", json={})
    assert res.status_code == 400


def test_能真删():
    """⭐ 记忆不是留痕：用户说删就**真删**（不是软删、不是隐藏）。"""
    item_id = _post(kind="term", source="chiral", target="手性").json()["item"]["id"]
    res = client.delete(f"/api/memories/{item_id}")
    assert res.status_code == 200
    assert res.json() == {"deleted": True, "id": item_id}
    assert _rows() == []
    assert client.delete(f"/api/memories/{item_id}").status_code == 404


def test_看不到也改不到别人的记忆():
    """⭐ 归属：别人的记忆一律 404（不暴露"存在但无权限"）。"""
    create_user_row("other", "pw-for-test")
    with SessionLocal() as session:
        other_user_id = session.scalars(
            select(User.id).where(User.username == "other")
        ).one()
        session.add(
            MemoryItem(
                user_id=other_user_id,
                kind="term",
                source="chiral",
                target="别人的说法",
            )
        )
        session.commit()
        other_id = session.scalars(select(MemoryItem.id)).first()

    # 列表里看不见
    assert client.get("/api/memories").json()["items"] == []
    # 注入里也看不见
    assert client.get("/api/memories/resolve").json()["terms"] == {}
    # 改 / 删都是 404
    assert (
        client.patch(f"/api/memories/{other_id}", json={"target": "偷改"}).status_code
        == 404
    )
    assert client.delete(f"/api/memories/{other_id}").status_code == 404
    # 而且真的没被改动
    with SessionLocal() as session:
        assert session.get(MemoryItem, other_id).target == "别人的说法"


def test_按kind筛与全量计数分开():
    """⭐ `counts` 用**全量**：否则界面上"术语 1 条"与列表里 0 条会互相矛盾。"""
    client.post(
        "/api/memories", json={"kind": "term", "source": "chiral", "target": "手性"}
    )
    client.post(
        "/api/memories", json={"kind": "cite", "source": "default", "target": "numeric"}
    )
    data = client.get("/api/memories?kind=term").json()
    assert len(data["items"]) == 1
    assert data["counts"] == {"term": 1, "cite": 1}  # 计数不受筛选影响
    assert client.get("/api/memories?kind=乱写").status_code == 400


def test_记忆挂用户不挂任务():
    """⭐ 源文献删了记忆还在：表里**没有 task_id**，所以删任务不会连坐。"""
    item_id = _post(kind="term", source="chiral", target="手性").json()["item"]["id"]
    with SessionLocal() as session:
        row = session.get(MemoryItem, item_id)
        assert row.user_id == TEST_USER_ID
        assert not hasattr(row, "task_id")
