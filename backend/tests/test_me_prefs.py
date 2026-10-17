"""个人偏好（F 卡 N40/N41）的测试。

盯七件事（每条都对应一种"真会发生"的错法）：

1. ⭐ **没存过回空包**（不是 404）——前端靠它判断"该不该把本机那份推上来"；
2. ⭐ **整包覆盖**（PUT 语义）：第二次只给一个键，前一次的键**必须消失**，
   否则"删掉的偏好"会阴魂不散；
3. ⭐ **一个用户只一行**（`user_id` unique）：改两次不许堆成两行；
4. ⭐ **别人的偏好互不可见**（各回各的）；
5. ⭐ **坏输入 400 且说明原因**（不是静默丢字段）：非标量值 / 键太多 / 包太大；
6. ⭐ **坏数据不炸页面**：库里塞一段非法 JSON，GET 回空包而不是 500；
7. ⭐ **注销账号要把偏好一起清掉**（`user_id` 是 unique 的，留着就是孤儿行）。

⚠️ 不用 `tmp_path`（AGENTS.md：受限环境不可写）。
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from helpers import TEST_USER_ID, create_user_row
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import User, UserPrefs

client = TestClient(app)


def _rows() -> list[UserPrefs]:
    with SessionLocal() as session:
        rows = list(session.scalars(select(UserPrefs).order_by(UserPrefs.id)).all())
        for row in rows:
            session.expunge(row)
    return rows


def _wipe() -> None:
    with SessionLocal() as session:
        for row in session.scalars(select(UserPrefs)).all():
            session.delete(row)
        session.commit()


def _get(**kwargs):
    return client.get("/api/me/preferences", **kwargs)


def _put(prefs, **kwargs):
    return client.put("/api/me/preferences", json={"prefs": prefs}, **kwargs)


def _other_user_headers() -> dict[str, str]:
    create_user_row("other", "pw-for-test")
    with SessionLocal() as session:
        other_id = session.scalar(select(User.id).where(User.username == "other"))
    from app.auth import create_session

    with SessionLocal() as session:
        user = session.get(User, other_id)
        token = create_session(session, user)
        session.commit()
    return {"Authorization": f"Bearer {token}"}


def test_no_row_returns_empty_object():
    """没存过 → 空包（不是 404）。"""
    _wipe()
    res = _get()
    assert res.status_code == 200
    assert res.json()["prefs"] == {}


def test_put_then_get_roundtrip():
    _wipe()
    prefs = {"defaultView": "dual", "tier": "fast", "readingSize": "large"}
    res = _put(prefs)
    assert res.status_code == 200
    assert res.json()["prefs"] == prefs
    assert res.json()["updated_at"]

    assert _get().json()["prefs"] == prefs


def test_put_replaces_whole_object():
    """⭐ 整包覆盖：第二次不给的键必须消失（PUT 语义，不是 merge）。"""
    _wipe()
    _put({"defaultView": "dual", "tier": "fast", "reducedMotion": True})
    res = _put({"defaultView": "mono"})
    assert res.status_code == 200
    assert res.json()["prefs"] == {"defaultView": "mono"}
    assert _get().json()["prefs"] == {"defaultView": "mono"}


def test_one_row_per_user():
    """⭐ 改两次只有一行（user_id unique）。"""
    _wipe()
    _put({"a": 1})
    _put({"b": 2})
    rows = [row for row in _rows() if row.user_id == TEST_USER_ID]
    assert len(rows) == 1
    assert json.loads(rows[0].payload) == {"b": 2}


def test_other_user_has_own_prefs():
    """⭐ 各回各的：别人那份我看不到，我写自己的也不碰他的。

    ⚠️ 仓库口径：**不切身份**（conftest 把鉴权依赖整个覆盖成固定用户了），
    所以"别人"的做法是**直接往库里插一行 `user_id=other`**，再用当前身份请求。
    """
    _wipe()
    create_user_row("other", "pw-for-test")
    with SessionLocal() as session:
        other_id = session.scalar(select(User.id).where(User.username == "other"))
        session.add(
            UserPrefs(user_id=other_id, payload=json.dumps({"defaultView": "mono"}))
        )
        session.commit()

    assert _get().json()["prefs"] == {}

    _put({"defaultView": "dual"})
    with SessionLocal() as session:
        other_row = session.scalar(
            select(UserPrefs).where(UserPrefs.user_id == other_id)
        )
        assert json.loads(other_row.payload) == {"defaultView": "mono"}


def test_rejects_nested_value():
    """⭐ 值只能是标量：嵌套结构 400，并说明是哪个键。"""
    _wipe()
    res = _put({"weird": {"nested": 1}})
    assert res.status_code == 400
    assert "weird" in res.json()["detail"]


def test_rejects_too_many_keys():
    _wipe()
    res = _put({f"k{i}": i for i in range(40)})
    assert res.status_code == 400
    assert "太多" in res.json()["detail"]


def test_rejects_oversized_payload():
    _wipe()
    res = _put({"blob": "字" * 9000})
    assert res.status_code == 400
    assert "太大" in res.json()["detail"]


def test_bad_stored_json_returns_empty_not_500():
    """⭐ 库里是脏数据（手写坏的）→ 空包，不 500。"""
    _wipe()
    with SessionLocal() as session:
        session.add(UserPrefs(user_id=TEST_USER_ID, payload="{not json"))
        session.commit()
    res = _get()
    assert res.status_code == 200
    assert res.json()["prefs"] == {}


def test_delete_account_purges_prefs():
    """⭐ 注销要把偏好一起清（`user_id` 是 unique，留着就是永远对不上人的孤儿行）。"""
    _wipe()
    _put({"defaultView": "dual"})
    assert _get().json()["prefs"] == {"defaultView": "dual"}

    # 二次确认在界面上做（`MeView.vue`），接口本身不带 confirm 字段
    res = client.delete("/api/me")
    assert res.status_code == 200

    with SessionLocal() as session:
        assert (
            session.scalar(select(UserPrefs).where(UserPrefs.user_id == TEST_USER_ID))
            is None
        )
