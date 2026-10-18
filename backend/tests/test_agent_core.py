"""Agent 层（P0）的四条底线。

1. **场景自描述**：`/api/agent/scenes` 能列出 read_ask（ready）
   与 write_compose（planned）；
2. ⭐ **密钥只写不读**：`GET /api/agent/config` 永不含明文；
   没 `DOCWISE_SECRET` 时拒绝落库（409）；
3. ⭐ **循环真的会调工具**：用 `FunctionModel` 离线跑一遍（不花 API 额度），
   验证工具被调用、轨迹可还原、出处只留工具真返回过的块号；
4. ⭐ **结构红线**：`packs/`、`scenes/` 里不许出现 `pydantic_ai`，
   只有 `runtime.py` 能 import；`[::1]` 的 NO_PROXY 也不会把模型构造弄崩。
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.agent import config_store, registry, runtime
from app.agent.scenes.read_ask import SCENE as READ_SCENE
from app.config import settings
from app.main import app

client = TestClient(app)
AGENT_DIR = Path("app/agent")


# ============================================================ ① 场景自描述
def test_scenes_endpoint_lists_ready_and_planned() -> None:
    body = client.get("/api/agent/scenes").json()
    items = {item["id"]: item for item in body["items"]}
    assert items["read_ask"]["status"] == "ready"
    # 写作的口子：列出来但标 planned（前端据此显示"即将开放"）
    assert items["write_compose"]["status"] == "planned"


# ============================================================ ② 密钥只写不读
def test_config_view_never_contains_secret() -> None:
    body = client.get("/api/agent/config").json()
    assert "api_key" not in body
    assert body["key_set"] is False
    # 预设厂商与档位映射要给前端（否则界面没法自描述）
    assert any(p["id"] == "deepseek" for p in body["providers"])
    assert "standard" in body["tier_models"]["deepseek"]


def test_saving_key_without_secret_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(settings, "docwise_secret", None)
    resp = client.put(
        "/api/agent/config",
        json={
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-test",
        },
    )
    assert resp.status_code == 409, resp.text
    assert "DOCWISE_SECRET" in resp.json()["detail"]


def test_saved_key_is_masked_and_round_trips(monkeypatch) -> None:
    monkeypatch.setattr(settings, "docwise_secret", "unit-test-secret")
    plain = "sk-abcdef123456"
    resp = client.put(
        "/api/agent/config",
        json={
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": plain,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["key_set"] is True
    assert plain not in str(body)          # ⭐ 明文绝不出现在响应里
    assert body["key_hint"].endswith("3456")

    # 库里存的是密文
    from app.db import SessionLocal
    from app.models import UserLLMConfig
    from tests.helpers import TEST_USER_ID

    with SessionLocal() as session:
        row = session.query(UserLLMConfig).filter_by(user_id=TEST_USER_ID).one()
        assert row.key_cipher and plain not in row.key_cipher

    # 解析出来能拿到原文（给 runtime 用）
    with SessionLocal() as session:
        resolved = config_store.resolve(session, TEST_USER_ID)
    assert resolved.api_key == plain

    # 清理：别把测试密钥留在库里影响别的用例
    from app.db import SessionLocal as SL

    with SL() as session:
        config_store.clear(session, TEST_USER_ID)


# ============================================================ ③ 循环真的调工具
def test_agent_loop_calls_tool_and_verifies_sources() -> None:
    from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    def script(messages, info: AgentInfo):
        tool_calls = [
            part
            for message in messages
            for part in message.parts
            if isinstance(part, ToolCallPart)
        ]
        if not tool_calls:
            return ModelResponse(
                parts=[ToolCallPart("search_library", {"query": "手性", "limit": 2})]
            )
        # 故意编一个不存在的块号，验证"编的会被剔掉"
        return ModelResponse(
            parts=[
                TextPart(
                    '{"answer":"库里有两篇讲手性的文献。",'
                    '"source_block_ids":["p0_b3","p9_b99"]}'
                )
            ]
        )

    # 用真的检索工具（先塞一条可命中的块）
    from app.db import SessionLocal
    from app.models import Task, TaskBlock
    from tests.helpers import TEST_USER_ID

    with SessionLocal() as session:
        task = Task(
            user_id=TEST_USER_ID,
            filename="chem_arXiv.pdf",
            status="completed",
            source_lang="en",
            target_lang="zh",
        )
        session.add(task)
        session.flush()
        session.add(
            TaskBlock(
                task_id=task.id,
                block_id="p0_b3",
                text="the chiral measures are conserved",
                translated="手性度量是守恒的",
            )
        )
        session.commit()
        task_id = task.id

    cfg = runtime.LLMConfig(
        base_url="http://127.0.0.1:1/v1", api_key="x", model="m"
    )
    result = asyncio.run(
        runtime.run_scene(
            READ_SCENE,
            "我库里有哪些讲手性的文献？",
            user_id=TEST_USER_ID,
            scope={"task_id": task_id},
            cfg=cfg,
            model=FunctionModel(script),
        )
    )

    assert "两篇" in result["answer"]
    kinds = [step["kind"] for step in result["steps"]]
    assert "tool_call" in kinds and "tool_result" in kinds
    assert result["steps"][0]["name"] == "search_library"
    # ⭐ 出处校验：真返回过的留下，编出来的删掉
    assert "p0_b3" in result["sources"]
    assert "p9_b99" in result["dropped_sources"]


# ============================================================ ④ 结构红线
def test_packs_and_scenes_never_import_framework() -> None:
    pattern = re.compile(r"^\s*(from|import)\s+pydantic_ai\b", re.M)
    offenders = []
    for path in list((AGENT_DIR / "packs").glob("*.py")) + list(
        (AGENT_DIR / "scenes").glob("*.py")
    ):
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(path.name)
    assert offenders == [], f"这些插件文件 import 了框架：{offenders}"


def test_only_runtime_imports_framework() -> None:
    pattern = re.compile(r"^\s*(from|import)\s+pydantic_ai\b", re.M)
    importers = [
        path.name
        for path in AGENT_DIR.glob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert importers == ["runtime.py"], f"只有 runtime.py 能 import，实际：{importers}"


def test_proxy_brackets_do_not_break_model_construction(monkeypatch) -> None:
    """`NO_PROXY=[::1]` 曾让 httpx 在 2026-10-08 直接崩（提问 500）。

    pydantic-ai 的 `httpx2` 是同一个坑：构造模型前必须洗环境。
    """
    monkeypatch.setenv("NO_PROXY", "localhost,[::1]")
    monkeypatch.setenv("no_proxy", "localhost,[::1]")
    cfg = runtime.LLMConfig(
        base_url="https://api.deepseek.com/v1",
        api_key="sk-x",
        model="deepseek-chat",
    )
    from pydantic_ai import Agent

    agent = runtime.build_agent(READ_SCENE, cfg)
    assert isinstance(agent, Agent)
    # 环境真的被洗过（方括号去掉）
    assert "[::1]" not in os.environ.get("NO_PROXY", "")


def test_registry_discovers_plugins() -> None:
    registry.reset_cache()
    assert "library" in registry.packs()
    assert "read_ask" in registry.scenes()
    names = {tool.name for tool in registry.tools_of(READ_SCENE)}
    assert "search_library" in names


# ============================================================ ⑤ 流式（SSE）
def test_chat_stream_emits_sse_frames(monkeypatch) -> None:
    """事件帧：`data: {json}` 一行一帧，类型是我们自己的名字。"""
    from app.agent import runtime

    async def fake_stream(scene, question, *, user_id, scope, cfg, model=None):
        yield {"type": "start", "scene": scene.id, "model": cfg.model}
        yield {"type": "tool_call", "name": "search_library", "args": {"query": "手性"}}
        yield {
            "type": "tool_result",
            "name": "search_library",
            "ok": True,
            "excerpt": "p0_b3",
        }
        yield {"type": "delta", "text": "库里有两篇"}
        yield {
            "type": "final",
            "answer": "库里有两篇",
            "sources": ["p0_b3"],
            "dropped_sources": [],
            "steps": [],
            "usage": {"requests": 1, "tool_calls": 1},
        }

    monkeypatch.setattr(runtime, "stream_scene", fake_stream)
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")

    resp = client.post(
        "/api/agent/chat/stream",
        json={"scene": "read_ask", "question": "我库里有什么"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")

    frames = [line for line in resp.text.splitlines() if line.startswith("data: ")]
    assert len(frames) == 5
    import json as _json

    payloads = [_json.loads(frame[len("data: ") :]) for frame in frames]
    assert [p["type"] for p in payloads] == [
        "start",
        "tool_call",
        "tool_result",
        "delta",
        "final",
    ]
    assert payloads[1]["name"] == "search_library"
    assert payloads[4]["sources"] == ["p0_b3"]


def test_chat_stream_rejects_unready_scene_before_streaming() -> None:
    """计划中的场景：**开流之前**就 400（不是流到一半才断）。"""
    resp = client.post(
        "/api/agent/chat/stream",
        json={"scene": "write_compose", "question": "试试"},
    )
    assert resp.status_code == 400
    assert "还没开放" in resp.json()["detail"]
