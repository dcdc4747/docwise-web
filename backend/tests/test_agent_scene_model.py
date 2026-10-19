"""每板块换模型：纯函数口径 + 端点行为（这是"会不会偷偷涨价"的把手）。

⚠️ 鉴权在 conftest 里已统一覆盖（测试默认"已登录"），所以这里**不登录**，
直接打端点——和仓库其它功能测试一致。

三条底线：
1. 不配就**跟随全局**（不能因为加了这功能就默认换更贵的模型）；
2. 只认白名单场景（存脏 key 不许生效）；
3. 请求里显式给的 model 优先于板块覆盖（"这一次临时用某个"）。
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.agent import config_store
from app.main import app

client = TestClient(app)


def test_scene_models_of_ignores_unknown_keys_and_junk() -> None:
    """只认白名单场景；坏 JSON 当空（不抛异常）。"""

    class Row:
        scene_models = json.dumps({"write_compose": "deepseek-reasoner", "nope": "x"})

    assert config_store.scene_models_of(Row()) == {"write_compose": "deepseek-reasoner"}

    class Broken:
        scene_models = "{not json"

    assert config_store.scene_models_of(Broken()) == {}
    assert config_store.scene_models_of(None) == {}


def test_put_scene_models_roundtrip_and_whitelist() -> None:
    """写进去能读回来；白名单外的键被丢掉；空串等于没配。"""
    res = client.put(
        "/api/agent/config",
        json={
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "tier": "standard",
            "scene_models": {"write_compose": "deepseek-reasoner", "read_ask": ""},
        },
    )
    assert res.status_code == 200, res.text
    view = client.get("/api/agent/config").json()
    assert view["scene_models"] == {"write_compose": "deepseek-reasoner"}

    client.put(
        "/api/agent/config",
        json={
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "tier": "standard",
            "scene_models": {"evil_scene": "some-expensive-model"},
        },
    )
    assert client.get("/api/agent/config").json()["scene_models"] == {}


def test_unset_means_follow_global() -> None:
    """什么都没配时，两个板块的 scene_model 都是空串（= 用全局那个）。"""
    client.put(
        "/api/agent/config",
        json={"base_url": "", "model": "", "tier": "standard", "scene_models": {}},
    )
    view = client.get("/api/agent/config").json()
    assert view.get("scene_models") == {}

    from helpers import TEST_USER_ID

    from app.db import SessionLocal

    with SessionLocal() as session:
        for scene_id in ("read_ask", "write_compose"):
            assert config_store.scene_model(session, TEST_USER_ID, scene_id) == ""
