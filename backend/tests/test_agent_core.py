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
from helpers import TEST_USER_ID

from app.agent import config_store, registry, runtime
from app.agent.scenes.read_ask import SCENE as READ_SCENE
from app.config import settings
from app.main import app

client = TestClient(app)
AGENT_DIR = Path("app/agent")


# ============================================================ ① 场景自描述
def test_scenes_endpoint_lists_ready_scenes() -> None:
    body = client.get("/api/agent/scenes").json()
    items = {item["id"]: item for item in body["items"]}
    # 读懂与写作**都已开放**（写作 2026-10-18 上线）
    assert items["read_ask"]["status"] == "ready"
    assert items["write_compose"]["status"] == "ready"
    # 写作场景要同时带两类工具：写作（草稿/素材）+ 查库（找依据）
    # 写作场景带四类工具：写作（草稿/素材）+ 查库（找依据）+ 术语 + 引文
    # 写作：读稿 + 找依据 + 术语 + 引文 + 自查 + 排版 + 素材 + 技能
    # （偏好写入让位给「改版式」，见 scenes/write_compose.py 注释；正好 15 个）
    assert set(items["write_compose"]["packs"]) == {
        "writing",
        "library",
        "terms",
        "cite",
        "check",
        "biblio",
        "materials",
        # 板块专属知识（体例/排版/改稿协议），按需加载
        "skills",
        # 改版式（服务端改 body_html + 存一版）
        "format",
    }
    # 读懂：定位文献 + 读段 + 术语 + 偏好 + 章节定位 + 文献对比 + 技能
    # （进度/重译让位给界面，见 scenes/read_ask.py 注释）
    assert set(items["read_ask"]["packs"]) == {
        "library",
        "terms",
        "tasks",
        "memory",
        "outline",
        "compare",
        "figures",
        "matrix",
        "skills",
    }
    # ⭐ 工具清单要能被前端/用户核对；同时钉住"别无限堆工具"的上限
    assert "search_library" in items["read_ask"]["tools"]
    assert "read_draft" in items["write_compose"]["tools"]
    assert "run_check" in items["write_compose"]["tools"]
    assert "list_figures" in items["read_ask"]["tools"]
    # 技能工具两侧都要有（板块专属知识按需取）；偏好写入已让位给界面
    assert "use_skill" in items["write_compose"]["tools"]
    assert "use_skill" in items["read_ask"]["tools"]
    assert 12 <= len(items["read_ask"]["tools"]) <= 15
    assert 12 <= len(items["write_compose"]["tools"]) <= 15
    # ⭐ 工具清单要能被前端/用户核对（文档与接口必须一一对应）
    assert "search_library" in items["read_ask"]["tools"]
    assert "read_draft" in items["write_compose"]["tools"]
    assert len(items["write_compose"]["tools"]) >= 8


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


def test_chat_stream_rejects_unready_scene_before_streaming(monkeypatch) -> None:
    """未开放的场景：**开流之前**就 400（不是流到一半才断）。

    ⚠️ 现在所有场景都 ready 了，所以这里注入一个 planned 场景来守规则——
    **不删这条**：以后再加新场景时，忘改 status 就靠它兜住。
    """
    from app.agent import registry
    from app.agent.contracts import Scene
    from app.agent.outputs import AskAnswer

    planned = Scene(
        id="not_yet",
        title="还没做的场景",
        system_prompt="",
        output_type=AskAnswer,
        packs=(),
        default_tier="standard",
        build_context=None,
        status="planned",
    )
    monkeypatch.setattr(registry, "scene_or_404", lambda scene_id: planned)
    resp = client.post(
        "/api/agent/chat/stream",
        json={"scene": "not_yet", "question": "试试"},
    )
    assert resp.status_code == 400
    assert "还没开放" in resp.json()["detail"]


# ============================================================ ⑥ 写作工具
def test_writing_pack_lists_and_reads_drafts() -> None:
    from app.agent.contracts import ToolContext
    from app.agent.packs import writing
    from app.db import SessionLocal
    from app.models import Draft

    with SessionLocal() as session:
        draft = Draft(
            user_id=TEST_USER_ID, title="手性论文初稿", body_md="第一段。" * 40
        )
        session.add(draft)
        session.commit()
        session.refresh(draft)
        draft_id = draft.id

    ctx = ToolContext(db=None, user_id=TEST_USER_ID, scene_id="write_compose", scope={})
    listed = writing.list_drafts(ctx)
    assert any(item["draft_id"] == draft_id for item in listed.data)

    # 不传 draft_id 时读 scope 里那篇
    ctx2 = ToolContext(
        db=None,
        user_id=TEST_USER_ID,
        scene_id="write_compose",
        scope={"draft_id": draft_id},
    )
    got = writing.read_draft(ctx2)
    assert got.data["draft_id"] == draft_id
    assert got.data["title"] == "手性论文初稿"
    assert got.data["chars"] > 0

    with SessionLocal() as session:
        session.delete(session.get(Draft, draft_id))
        session.commit()


def test_writing_pack_refuses_other_users_draft() -> None:
    """别人的草稿读不到——越权不能靠前端拦。"""
    from app.agent.contracts import ToolContext
    from app.agent.packs import writing
    from app.db import SessionLocal
    from app.models import Draft

    with SessionLocal() as session:
        other = Draft(user_id=TEST_USER_ID + 999, title="别人的稿", body_md="不该看到")
        session.add(other)
        session.commit()
        session.refresh(other)
        other_id = other.id

    ctx = ToolContext(db=None, user_id=TEST_USER_ID, scene_id="write_compose", scope={})
    got = writing.read_draft(ctx, {"draft_id": other_id})
    assert "找不到" in str(got.data)

    with SessionLocal() as session:
        session.delete(session.get(Draft, other_id))
        session.commit()


def test_materials_search_lives_in_one_place() -> None:
    """素材检索只有一处实现：`materials.list_materials`。

    2026-10-18 合并：`writing.search_materials` 退役——同一个能力两个工具名，
    模型会随机挑一个，行为还不一致（旧的不过滤软删、不转义通配符）。
    """
    from app.agent.contracts import ToolContext
    from app.agent.packs import materials as materials_pack
    from app.agent.packs import writing as writing_pack
    from app.db import SessionLocal
    from app.models import Material

    # ① 旧工具必须没了
    assert not hasattr(writing_pack, "search_materials")
    assert "search_materials" not in [t.name for t in writing_pack.PACK.tools]

    with SessionLocal() as session:
        hit = Material(
            user_id=TEST_USER_ID,
            text_quote="手性时间结构可以分成两部分",
            source_name="chem.pdf",
            page=3,
        )
        miss = Material(
            user_id=TEST_USER_ID,
            text_quote="稀疏线性系统的 Dixon 提升",
            source_name="math.pdf",
            page=7,
        )
        session.add_all([hit, miss])
        session.commit()
        hit_id, miss_id = hit.id, miss.id

    ctx = ToolContext(db=None, user_id=TEST_USER_ID, scene_id="write_compose", scope={})
    got = materials_pack.list_materials(ctx, {"query": "手性"})
    assert len(got.data) == 1
    assert got.data[0]["source"] == "chem.pdf"
    assert got.data[0]["page"] == 3

    with SessionLocal() as session:
        for material_id in (hit_id, miss_id):
            session.delete(session.get(Material, material_id))
        session.commit()



# ============================================================ ⑦ 改写建议校验
def test_verify_revisions_drops_unmatched() -> None:
    """对不上原文的建议必须被剔掉——否则用户点「采用」会把稿子改坏。"""
    from app.agent.contracts import ToolContext
    from app.agent.outputs import Revision, WriteAnswer
    from app.agent.scenes.write_compose import verify_revisions
    from app.db import SessionLocal
    from app.models import Draft

    with SessionLocal() as session:
        draft = Draft(
            user_id=TEST_USER_ID,
            title="校验用的稿",
            body_md="手性可以分成时间与空间两部分。这是第二句。",
        )
        session.add(draft)
        session.commit()
        session.refresh(draft)
        draft_id = draft.id

    ctx = ToolContext(
        db=None,
        user_id=TEST_USER_ID,
        scene_id="write_compose",
        scope={"draft_id": draft_id},
    )
    output = WriteAnswer(
        answer="给了两条建议",
        revisions=[
            Revision(
                original="手性可以分成时间与空间两部分。",
                revised="手性可分解为时间与空间两个维度。",
                reason="更贴学科用语",
            ),
            Revision(original="这句稿子里根本没有", revised="随便改", reason="编的"),
        ],
    )
    kept, notes = verify_revisions(ctx, output)
    assert len(kept.revisions) == 1
    assert kept.revisions[0].original.startswith("手性可以分成")
    assert any("剔掉 1 条" in n for n in notes)

    with SessionLocal() as session:
        session.delete(session.get(Draft, draft_id))
        session.commit()


# ============================================================ ⑧ 新工具箱
def test_terms_pack_reads_and_filters() -> None:
    """术语表：能读、能按关键词过滤、坏的 JSON 不炸。"""
    import json as _json

    from app.agent.contracts import ToolContext
    from app.agent.packs import terms as terms_pack
    from app.db import SessionLocal
    from app.models import Task, TaskUnderstanding

    with SessionLocal() as session:
        task = Task(user_id=TEST_USER_ID, filename="术语用例.pdf", status="completed")
        session.add(task)
        session.commit()
        session.refresh(task)
        session.add(
            TaskUnderstanding(
                task_id=task.id,
                guide_json=None,
                terms_json=_json.dumps(
                    {"terms": [{"source": "chirality", "target": "手性"}]},
                    ensure_ascii=False,
                ),
                status="ready",
            )
        )
        session.commit()
        task_id = task.id

    ctx = ToolContext(db=None, user_id=TEST_USER_ID, scene_id="read_ask", scope={})
    all_terms = terms_pack.search_terms(ctx, {})
    assert any(item["translation"] == "手性" for item in all_terms.data)

    filtered = terms_pack.search_terms(ctx, {"query": "chirality"})
    assert len(filtered.data) == 1
    assert filtered.data[0]["task_id"] == task_id

    with SessionLocal() as session:
        session.query(TaskUnderstanding).filter_by(task_id=task_id).delete()
        session.delete(session.get(Task, task_id))
        session.commit()


def test_tasks_pack_locates_my_documents_only() -> None:
    """列文献只能列自己的；别人的看不见。"""
    from app.agent.contracts import ToolContext
    from app.agent.packs import tasks as tasks_pack
    from app.db import SessionLocal
    from app.models import Task

    with SessionLocal() as session:
        mine = Task(
            user_id=TEST_USER_ID, filename="我的手性论文.pdf", status="completed"
        )
        other = Task(
            user_id=TEST_USER_ID + 999, filename="别人的.pdf", status="completed"
        )
        session.add_all([mine, other])
        session.commit()
        session.refresh(mine)
        session.refresh(other)
        mine_id, other_id = mine.id, other.id

    ctx = ToolContext(db=None, user_id=TEST_USER_ID, scene_id="read_ask", scope={})
    listed = tasks_pack.list_tasks(ctx, {"query": "手性"})
    ids = [item["task_id"] for item in listed.data]
    assert mine_id in ids
    assert other_id not in ids

    with SessionLocal() as session:
        for task_id in (mine_id, other_id):
            session.delete(session.get(Task, task_id))
        session.commit()


def test_cite_pack_lists_citations_without_writing_anything() -> None:
    """引文工具只读：空草稿返回空列表，且不会往库里插东西。"""
    from app.agent.contracts import ToolContext
    from app.agent.packs import cite as cite_pack
    from app.db import SessionLocal
    from app.models import Citation, Draft

    with SessionLocal() as session:
        draft = Draft(user_id=TEST_USER_ID, title="引文用例", body_md="正文")
        session.add(draft)
        session.commit()
        session.refresh(draft)
        draft_id = draft.id

    ctx = ToolContext(
        db=None,
        user_id=TEST_USER_ID,
        scene_id="write_compose",
        scope={"draft_id": draft_id},
    )
    got = cite_pack.list_citations(ctx, {})
    assert got.data == []

    with SessionLocal() as session:
        count = session.query(Citation).filter_by(draft_id=draft_id).count()
        assert count == 0, "读工具不许写库"
        session.delete(session.get(Draft, draft_id))
        session.commit()


# ============================================================ ⑨ 工具箱契约（框架级）
def test_every_pack_obeys_the_tool_contract() -> None:
    """所有包一起过一遍契约：名字唯一、schema 是 object、handler 签名对。"""
    import inspect

    from app.agent import registry

    pack_names: list[str] = []
    tool_names: list[str] = []
    for pack in registry.packs().values():
        pack_names.append(pack.name)
        for spec in pack.tools:
            tool_names.append(spec.name)

            # ① 名字与描述不能空（模型靠 description 选工具）
            assert spec.name, f"{pack.name} 里有工具没名字"
            assert spec.description.strip(), f"{spec.name} 没有 description"

            # ② 参数必须是 object 型 JSON Schema
            assert spec.parameters.get("type") == "object", (
                f"{spec.name} 的 parameters 不是 object schema"
            )

            # ③ handler 必须是 (ctx, args) 两个参数（runtime 就是这么调的）
            params = list(inspect.signature(spec.handler).parameters)
            assert len(params) == 2, (
                f"{spec.name} 的 handler 必须是 (ctx, args)，现在是 {params}"
            )

    # ④ 包名、工具名都要唯一
    assert len(pack_names) == len(set(pack_names)), f"包名重复：{pack_names}"
    assert len(tool_names) == len(set(tool_names)), (
        f"工具名重复：{[n for n in tool_names if tool_names.count(n) > 1]}"
    )


def test_packs_and_scenes_never_import_the_engine() -> None:
    """结构红线：`packs/`、`scenes/` 只认我们的 ABI，不认引擎。"""
    import re

    pattern = re.compile(r"^\s*(from|import)\s+pydantic_ai\b", re.M)
    offenders = []
    for folder in ("packs", "scenes"):
        for path in (AGENT_DIR / folder).glob("*.py"):
            if pattern.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path))
    assert not offenders, f"这些文件直接 import 了引擎：{offenders}"


def test_verify_revisions_accepts_whole_paragraph() -> None:
    """整段（多句）替换也要能通过校验。"""
    from app.agent.contracts import ToolContext
    from app.agent.outputs import Revision, WriteAnswer
    from app.agent.scenes.write_compose import verify_revisions
    from app.db import SessionLocal
    from app.models import Draft

    paragraph = (
        "相关研究表明，消费者面对 AI 生成内容时往往呈现算法欣赏与算法厌恶并存的态度。"
        "一方面认可效率优势，另一方面又因缺乏人类经验而产生抵触。"
    )
    with SessionLocal() as session:
        draft = Draft(
            user_id=TEST_USER_ID,
            title="整段改写",
            body_md=f"前言。\n{paragraph}\n后记。",
        )
        session.add(draft)
        session.commit()
        session.refresh(draft)
        draft_id = draft.id

    ctx = ToolContext(
        db=None,
        user_id=TEST_USER_ID,
        scene_id="write_compose",
        scope={"draft_id": draft_id},
    )
    output = WriteAnswer(
        answer="整段重写一版",
        revisions=[
            Revision(
                original=paragraph,
                revised="杨娟等基于漂移扩散模型发现…（整段重写）",
                reason="去掉悬空引证",
            )
        ],
    )
    kept, notes = verify_revisions(ctx, output)
    assert len(kept.revisions) == 1, notes

    with SessionLocal() as session:
        session.delete(session.get(Draft, draft_id))
        session.commit()


def test_verify_revisions_ignores_line_ending_difference() -> None:
    """草稿是 \r\n、模型给 \n —— 不能因为换行符不同就判"对不上"。"""
    from app.agent.contracts import ToolContext
    from app.agent.outputs import Revision, WriteAnswer
    from app.agent.scenes.write_compose import verify_revisions
    from app.db import SessionLocal
    from app.models import Draft

    with SessionLocal() as session:
        draft = Draft(
            user_id=TEST_USER_ID,
            title="换行差异",
            body_md="第一句。\r\n第二句。\r\n第三句。",
        )
        session.add(draft)
        session.commit()
        session.refresh(draft)
        draft_id = draft.id

    ctx = ToolContext(
        db=None,
        user_id=TEST_USER_ID,
        scene_id="write_compose",
        scope={"draft_id": draft_id},
    )
    # 模型给的是 \n（这是最常见的情况）
    output = WriteAnswer(
        answer="",
        revisions=[
            Revision(
                original="第一句。\n第二句。",
                revised="第一句。第二句（合并成一句）。",
                reason="合并",
            )
        ],
    )
    kept, notes = verify_revisions(ctx, output)
    assert len(kept.revisions) == 1, f"换行差异被误判：{notes}"

    with SessionLocal() as session:
        session.delete(session.get(Draft, draft_id))
        session.commit()


def test_verified_block_ids_reads_full_tool_output() -> None:
    """出处校验要读到**完整**工具结果，不能只看截断的 excerpt。

    实测背景（task 41 问「这篇有几张图」）：`list_figures` 返回 8 条图注，
    但流式事件的 excerpt 只有 400 字（甚至为 None），
    后两条的 `p7_b99` / `p7_b100` 因此被当成"编造出处"剔掉。
    """
    from pydantic_ai.messages import ModelRequest, ModelResponse, ToolReturnPart

    from app.agent.runtime import _verified_block_ids

    # 工具返回很多块号：把它们都塞进一条 ToolReturnPart
    long_body = [{"block_id": f"p7_b{i}", "text": "x" * 50} for i in range(90, 110)]
    messages = [
        ModelRequest(parts=[]),
        ModelResponse(
            parts=[
                ToolReturnPart(
                    tool_name="list_figures",
                    content=long_body,
                    tool_call_id="c1",
                )
            ]
        ),
    ]

    ids = _verified_block_ids(messages)
    # 后面的（第 99、100 条）也必须被认出来——它们离头部很远
    assert "p7_b99" in ids
    assert "p7_b100" in ids
    assert len(ids) == 20


def test_verified_block_ids_ignores_failed_retry() -> None:
    """重试提示（RetryPromptPart）里出现的块号不算"工具返回过"。"""
    from pydantic_ai.messages import ModelResponse, RetryPromptPart

    from app.agent.runtime import _verified_block_ids

    messages = [
        ModelResponse(
            parts=[
                RetryPromptPart(
                    content="参数不对，p0_b1 不存在",
                    tool_name="read_blocks",
                    tool_call_id="c1",
                )
            ]
        )
    ]
    assert _verified_block_ids(messages) == set()


def test_get_understanding_survives_list_shaped_terms() -> None:
    """术语表是**数组**时也要能返回（截图里的崩溃点）。"""
    import json as _json

    from app.agent.contracts import ToolContext
    from app.agent.packs import tasks as tasks_pack
    from app.db import SessionLocal
    from app.models import Task, TaskUnderstanding

    with SessionLocal() as session:
        task = Task(user_id=TEST_USER_ID, filename="术语数组.pdf", status="completed")
        session.add(task)
        session.commit()
        session.refresh(task)
        session.add(
            TaskUnderstanding(
                task_id=task.id,
                guide_json=_json.dumps(
                    {
                        "research_question": {
                            "text": "研究手性",
                            "source_block_ids": ["p0_b1"],
                        }
                    },
                    ensure_ascii=False,
                ),
                # ⚠️ 数组形状：这正是线上让工具崩掉的形状
                terms_json=_json.dumps(
                    [
                        {"term": "chirality", "cn": "手性"},
                        {"term": "wavepacket", "cn": "波包"},
                    ],
                    ensure_ascii=False,
                ),
                status="ready",
            )
        )
        session.commit()
        task_id = task.id

    ctx = ToolContext(db=None, user_id=TEST_USER_ID, scene_id="read_ask", scope={})
    got = tasks_pack.get_understanding(ctx, {"task_id": task_id})
    assert isinstance(got.data, dict), got.data
    assert got.data["terms_count"] == 2
    assert got.data["guide"]["research_question"]["text"] == "研究手性"

    with SessionLocal() as session:
        session.query(TaskUnderstanding).filter_by(task_id=task_id).delete()
        session.delete(session.get(Task, task_id))
        session.commit()


def test_verify_writes_drops_bad_anchor() -> None:
    """直接写正文的操作：锚点必须逐字在稿子里，否则丢掉（编锚点会把稿子写乱）。"""
    from app.agent.contracts import ToolContext
    from app.agent.outputs import WriteAnswer, WriteOp
    from app.agent.scenes.write_compose import verify_writes
    from app.db import SessionLocal
    from app.models import Draft

    with SessionLocal() as session:
        draft = Draft(
            user_id=TEST_USER_ID,
            title="写入用例",
            body_md="一、引言\n\n手性可以分成时间与空间两部分。",
        )
        session.add(draft)
        session.commit()
        session.refresh(draft)
        draft_id = draft.id

    ctx = ToolContext(
        db=None,
        user_id=TEST_USER_ID,
        scene_id="write_compose",
        scope={"draft_id": draft_id},
    )
    output = WriteAnswer(
        answer="写了两段",
        ops=[
            # 合法：追加（不需要锚点）
            WriteOp(mode="append", text="二、方法\n\n本文用……", reason="补一节"),
            # 合法：锚点是原文
            WriteOp(
                mode="insert_after",
                text="（这里补一句依据）",
                anchor="手性可以分成时间与空间两部分。",
                reason="续写",
            ),
            # 非法：锚点不存在
            WriteOp(
                mode="replace",
                text="乱写",
                anchor="这句稿子里没有",
                reason="编的",
            ),
            # 非法：空文本
            WriteOp(mode="append", text="   ", reason="空"),
            # 非法：未知 mode
            WriteOp(mode="delete_all", text="x", reason="想删库"),
        ],
    )
    kept, notes = verify_writes(ctx, output)
    assert len(kept.ops) == 2, [op.mode for op in kept.ops]
    assert {op.mode for op in kept.ops} == {"append", "insert_after"}
    assert any("剔掉 3 条" in n for n in notes)

    with SessionLocal() as session:
        session.delete(session.get(Draft, draft_id))
        session.commit()


def test_run_scene_carries_write_ops() -> None:
    """写作场景：模型给的 ops 要出现在返回里（前端靠它落笔）。"""
    import json

    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import FunctionModel

    from app.agent.scenes.write_compose import SCENE as WRITE_SCENE
    from app.db import SessionLocal
    from app.models import Draft

    with SessionLocal() as session:
        draft = Draft(
            user_id=TEST_USER_ID,
            title="代写用例",
            body_md="## 一、引言\n\n手性可以分成时间与空间两部分。",
        )
        session.add(draft)
        session.commit()
        session.refresh(draft)
        draft_id = draft.id

    def script(messages, info):  # noqa: ANN001 —— 直接给最终答案，不调工具
        payload = {
            "answer": "写好了",
            "source_block_ids": [],
            "revisions": [],
            "ops": [
                {
                    "mode": "insert_after",
                    "anchor": "手性可以分成时间与空间两部分。",
                    "text": "这里的「时间」指的是时序演化的手性。",
                    "reason": "补一句定义",
                }
            ],
        }
        body = json.dumps(payload, ensure_ascii=False)
        return ModelResponse(parts=[TextPart(content=body)])

    cfg = runtime.LLMConfig(base_url="http://127.0.0.1:1/v1", api_key="x", model="m")
    result = asyncio.run(
        runtime.run_scene(
            WRITE_SCENE,
            "补一句定义，直接写进正文",
            user_id=TEST_USER_ID,
            scope={"draft_id": draft_id},
            cfg=cfg,
            model=FunctionModel(script),
        )
    )

    assert result["ops"], f"返回里没有 ops：{list(result)}"
    op = result["ops"][0]
    assert op["mode"] == "insert_after"
    assert op["anchor"] == "手性可以分成时间与空间两部分。"
    assert "时序演化" in op["text"]

    with SessionLocal() as session:
        session.delete(session.get(Draft, draft_id))
        session.commit()


def test_partial_json_string_grows_with_the_stream() -> None:
    """流式 JSON 里逐段长出 `answer`（前端靠它做打字机效果）。

    这是"憋一大坨"那个体验问题的根：结构化输出下答案是 `final_result` 的 JSON 参数流，
    必须先能**边收边剥**，否则只能等最后一次性显示。
    """
    from app.agent.runtime import _partial_json_string

    # 逐段喂，每次都应该拿到"目前能确定的那部分"
    chunks = [
        '{"ans',
        '{"answer"',
        '{"answer": "手性',
        '{"answer": "手性可以从',
        '{"answer": "手性可以从空间反演',
    ]
    seen = [_partial_json_string(text, "answer") for text in chunks]
    assert seen[0] == ""  # key 还没到
    assert seen[1] == ""
    assert seen[2] == "手性"
    assert seen[3] == "手性可以从"
    assert seen[4] == "手性可以从空间反演"
    # 单调递增（前端按"新增部分"发 delta，必须只增不减）
    assert all(len(a) <= len(b) for a, b in zip(seen, seen[1:]))


def test_partial_json_string_handles_escapes_and_partial_escape() -> None:
    """转义要正确解码，且**没写完的转义**不许吐出半个字。"""
    from app.agent.runtime import _partial_json_string

    line = _partial_json_string('{"answer": "第一行\\n第二行"}', "answer")
    assert line == "第一行\n第二行"
    quoted = _partial_json_string('{"answer": "引号\\"在里面"}', "answer")
    assert quoted == '引号"在里面'
    # `\u` 还差字符时停住，等下一批
    assert _partial_json_string('{"answer": "a\\u4e2"}', "answer") == "a"
    assert _partial_json_string('{"answer": "a\\u4e2d"}', "answer") == "a中"
    # 结尾停在反斜杠上（转义还没写完）也不许吐半个字
    assert _partial_json_string('{"answer": "abc\\', "answer") == "abc"
