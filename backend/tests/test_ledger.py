"""环节台账（契约 §2.5 / N15–N17）的测试。

盯四件事：

1. ⭐ **写入函数**：字段齐全地写进去；**失败绝不抛**（台账是记录、不是业务）；
   缺必填字段**跳过**而不是写半条；超长字段**截断**而不是丢事件；
2. ⭐ **问答与台账同源**：回答问题时服务端就写了一条（`stage="ask"`），
   `GET /api/ask-logs` 读的就是它——**没有第二份数据、也没有第二张表**；
3. ⭐ **actor 是"数据流向"的证据**：全文/检索两条路调了模型（`api`），
   检索没召回时**一次模型都没调**（`local`）——这两件事不许长一个样；
4. ⭐ **引擎那三件真发生过的事**（取字 / OCR / 翻译）进了台账，失败也如实记。

⚠️ 不用 `tmp_path`（AGENTS.md：受限环境不可写）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import TEST_USER_ID, create_user_row
from sqlalchemy import select

from app import ledger
from app.db import SessionLocal
from app.engine import TaskState
from app.main import app
from app.models import MemoryEvent, Task, TaskBlock
from app.worker import TranslationWorker

FAKE_ANSWER = {"answer": "答案是手性测度守恒。", "source_block_ids": ["p0_b1"]}


def _make_task(*, user_id: int = TEST_USER_ID, filename: str = "chem.pdf") -> int:
    with SessionLocal() as session:
        row = Task(user_id=user_id, filename=filename, status="completed")
        session.add(row)
        session.commit()
        return row.id


def _make_block(
    *, task_id: int, block_id: str = "p0_b1", text: str = "手性测度守恒"
) -> None:
    with SessionLocal() as session:
        session.add(TaskBlock(task_id=task_id, block_id=block_id, text=text))
        session.commit()


def _events(*, task_id: int | None = None) -> list[MemoryEvent]:
    """把事件行读出来（按 id 升序，脱离会话返回，测试里可直接断言）。"""
    with SessionLocal() as session:
        stmt = select(MemoryEvent).order_by(MemoryEvent.id)
        if task_id is not None:
            stmt = stmt.where(MemoryEvent.task_id == task_id)
        rows = list(session.scalars(stmt).all())
        for row in rows:
            session.expunge(row)
        return rows


def _mine(*, stage: str) -> list[MemoryEvent]:
    return [row for row in _events() if row.stage == stage]


# ============================================================ 写入函数


def test_record_event_writes_all_fields() -> None:
    task_id = _make_task()
    event_id = ledger.record_event(
        user_id=TEST_USER_ID,
        task_id=task_id,
        stage="ask",
        actor="api",
        tool="model-api",
        summary="回答提问：这段什么意思？｜出处 1 条",
        payload={"question": "这段什么意思？"},
    )

    assert event_id is not None
    rows = _events(task_id=task_id)
    assert len(rows) == 1
    row = rows[0]
    assert (row.id, row.user_id, row.layer) == (event_id, TEST_USER_ID, "L0")
    assert (row.stage, row.actor, row.tool) == ("ask", "api", "model-api")
    assert row.payload == {"question": "这段什么意思？"}
    assert row.created_at is not None


def test_record_event_swallows_failures(monkeypatch) -> None:
    """台账写失败**绝不能**影响主流程：只记日志、返回 None，不抛。"""

    def boom():
        raise RuntimeError("库挂了")

    monkeypatch.setattr(ledger, "SessionLocal", boom)
    assert (
        ledger.record_event(
            user_id=TEST_USER_ID,
            stage="extract",
            actor="local",
            summary="抽取文字层：1 块",
        )
        is None
    )


def test_record_event_skips_incomplete_events() -> None:
    """缺必填字段就不写——**半条比没有更糟**（界面会当真）。"""
    assert (
        ledger.record_event(
            user_id=TEST_USER_ID, stage="extract", actor="local", summary=""
        )
        is None
    )
    assert (
        ledger.record_event(user_id=TEST_USER_ID, stage="", actor="local", summary="x")
        is None
    )
    assert _events() == []


def test_record_event_truncates_over_long_values() -> None:
    """超长就截断到列宽，**不是**把整条事件丢掉。"""
    event_id = ledger.record_event(
        user_id=TEST_USER_ID, stage="extract", actor="local", summary="长" * 900
    )
    assert event_id is not None
    rows = _events()
    assert len(rows) == 1
    assert len(rows[0].summary) == 500


# ============================================================ N15 / N16


def test_ask_log_round_trip() -> None:
    task_id = _make_task()
    with TestClient(app) as client:
        created = client.post(
            "/api/ask-logs",
            json={
                "task_id": task_id,
                "question": "这段什么意思？",
                "answer": "讲的是手性测度。",
                "source_block_ids": ["p0_b1"],
            },
        )
        listed = client.get("/api/ask-logs", params={"task_id": task_id})

    assert created.status_code == 201, created.text
    assert set(created.json().keys()) == {"id"}
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["question"] == "这段什么意思？"
    assert items[0]["answer"] == "讲的是手性测度。"
    assert items[0]["source_block_ids"] == ["p0_b1"]
    assert items[0]["task_id"] == task_id
    assert items[0]["created_at"].endswith("+00:00")  # 时间一律带时区


def test_ask_logs_are_scoped_to_me() -> None:
    other_id = create_user_row("other-user", "pw-12345678")
    theirs = _make_task(user_id=other_id, filename="theirs.pdf")
    mine = _make_task(filename="mine.pdf")

    with TestClient(app) as client:
        foreign = client.post(
            "/api/ask-logs",
            json={
                "task_id": theirs,
                "question": "别人的文献",
                "answer": "x",
                "source_block_ids": [],
            },
        )
        listed_foreign = client.get("/api/ask-logs", params={"task_id": theirs})
        ledger.record_event(
            user_id=other_id,
            task_id=theirs,
            stage="ask",
            actor="api",
            summary="别人的问答",
        )
        # 我自己也写一条：这样"只看得见自己的"才是真的被断言到（而不是空列表巧合）
        mine_created = client.post(
            "/api/ask-logs",
            json={
                "task_id": mine,
                "question": "我的文献",
                "answer": "y",
                "source_block_ids": [],
            },
        )
        mine_only = client.get("/api/ask-logs")

    assert foreign.status_code == 404, foreign.text
    assert listed_foreign.status_code == 404  # 连读都不给读别人的
    assert mine_created.status_code == 201, mine_created.text
    assert [item["task_id"] for item in mine_only.json()["items"]] == [mine]


# ============================================================ N17


def test_memory_events_filters_and_limit() -> None:
    task_id = _make_task()
    with TestClient(app) as client:
        for stage, layer in (("extract", "L0"), ("ask", "L0"), ("cite", "L1")):
            resp = client.post(
                "/api/memory-events",
                json={
                    "task_id": task_id,
                    "stage": stage,
                    "actor": "local",
                    "summary": f"{stage} 发生过",
                    "layer": layer,
                },
            )
            assert resp.status_code == 201, resp.text

        all_rows = client.get("/api/memory-events", params={"task_id": task_id})
        by_layer = client.get("/api/memory-events", params={"layer": "L1"})
        limited = client.get("/api/memory-events", params={"limit": 1})
        clamped = client.get("/api/memory-events", params={"limit": 0})

    assert len(all_rows.json()["items"]) == 3
    assert [row["stage"] for row in by_layer.json()["items"]] == ["cite"]
    assert len(limited.json()["items"]) == 1
    assert len(clamped.json()["items"]) == 1  # 越界夹到 1，不是静默变 0


def test_memory_events_contract_shape() -> None:
    """形状与 `me._memory_event_view` 一致（N17 与 N26 同源，不许两份形状）。"""
    with TestClient(app) as client:
        client.post(
            "/api/memory-events",
            json={"stage": "ocr", "actor": "local", "summary": "OCR 识别：3 段"},
        )
        row = client.get("/api/memory-events").json()["items"][0]

    assert set(row.keys()) == {
        "id",
        "task_id",
        "layer",
        "stage",
        "actor",
        "tool",
        "summary",
        "payload",
        "created_at",
    }


# ============================================================ 真链路


def test_ask_endpoint_writes_ledger_row(monkeypatch) -> None:
    """⭐ 走真接口问一次 → 台账里**真的多了一条**（证明写进去了，不是"函数能跑"）。"""
    task_id = _make_task()
    _make_block(task_id=task_id)
    monkeypatch.setattr("app.routers.ask.answer_question", lambda *a, **k: FAKE_ANSWER)

    with TestClient(app) as client:
        asked = client.post(
            f"/api/tasks/{task_id}/ask", json={"question": "讲了什么？"}
        )
        logs = client.get("/api/ask-logs", params={"task_id": task_id})
        events = client.get("/api/memory-events", params={"task_id": task_id})

    assert asked.status_code == 200, asked.text
    assert asked.json()["mode"] == "full_context"

    items = logs.json()["items"]
    assert len(items) == 1, "服务端答题时就该写一条问答台账"
    assert items[0]["question"] == "讲了什么？"
    assert items[0]["answer"] == FAKE_ANSWER["answer"]

    ask_events = [row for row in events.json()["items"] if row["stage"] == "ask"]
    assert len(ask_events) == 1
    assert ask_events[0]["actor"] == "api"  # 这条真的调了模型
    assert ask_events[0]["tool"] == "model-api"


def test_ask_no_hit_records_local_event(monkeypatch) -> None:
    """⭐ 检索没召回 → **一次模型都没调**，台账必须如实写 `local`。"""
    task_id = _make_task()
    _make_block(task_id=task_id)
    monkeypatch.setattr("app.routers.ask.answer_question", lambda *a, **k: FAKE_ANSWER)
    monkeypatch.setattr("app.routers.ask._fts_search", lambda *a, **k: [])
    monkeypatch.setattr(
        "app.routers.ask.settings.docwise_ask_full_context_max_chars", 1, raising=False
    )

    with TestClient(app) as client:
        asked = client.post(
            f"/api/tasks/{task_id}/ask", json={"question": "讲了什么？"}
        )
        events = client.get("/api/memory-events", params={"task_id": task_id})

    assert asked.status_code == 200, asked.text
    assert asked.json()["source_block_ids"] == []
    row = events.json()["items"][0]
    assert row["actor"] == "local"
    assert row["tool"] == "fts"
    assert row["payload"]["called_model"] is False


def test_understanding_generation_writes_event(monkeypatch) -> None:
    """导读/术语生成一次 → 台账一条（`actor=api`，那是发往云端模型的那条路）。"""
    task_id = _make_task()
    _make_block(task_id=task_id)
    monkeypatch.setattr(
        "app.routers.tasks.extract_understanding",
        lambda items: {
            "research_question": {"text": "问题", "source_block_ids": ["p0_b1"]},
            "terms": [{"term": "chirality", "cn": "手性", "definition": "x"}],
        },
    )

    with TestClient(app) as client:
        resp = client.post(f"/api/tasks/{task_id}/understanding")
        events = client.get("/api/memory-events", params={"task_id": task_id})

    assert resp.status_code == 200, resp.text
    rows = [row for row in events.json()["items"] if row["stage"] == "understanding"]
    assert len(rows) == 1
    assert rows[0]["actor"] == "api"
    assert "1 条术语" in rows[0]["summary"]


def test_pipeline_events_record_extract_ocr_and_translate() -> None:
    """引擎那三件事：文字层 / OCR / 翻译（块级译文为 0 时**不许**写"翻译完成"）。"""
    task_id = _make_task()
    TranslationWorker._record_pipeline_events(
        task_id=task_id,
        owner_id=TEST_USER_ID,
        terminal=TaskState.COMPLETED.value,
        mode="text-layer",
        blocks_total=42,
        blocks_translated=42,
        error=None,
    )
    TranslationWorker._record_pipeline_events(
        task_id=task_id,
        owner_id=TEST_USER_ID,
        terminal=TaskState.COMPLETED.value,
        mode="ocr",
        blocks_total=73,
        blocks_translated=0,
        error=None,
    )

    summaries = [row.summary for row in _events(task_id=task_id)]
    assert "抽取文字层：42 块" in summaries
    assert "翻译完成：42/42 块有译文" in summaries
    assert "OCR 识别：73 段（本地模型，离线）" in summaries
    # ⚠️ OCR 那篇没有块级译文 → 只如实说"未产生块级译文"，不写"翻译完成"
    assert not [text for text in summaries if "翻译完成：0/" in text]
    assert [text for text in summaries if "未产生块级译文" in text]


def test_pipeline_failure_is_recorded_as_unfinished() -> None:
    """没跑完就如实写"未完成"，**不写"翻译完成"**。"""
    task_id = _make_task()
    TranslationWorker._record_pipeline_events(
        task_id=task_id,
        owner_id=TEST_USER_ID,
        terminal=TaskState.FAILED.value,
        mode="text-layer",
        blocks_total=0,
        blocks_translated=0,
        error="引擎崩了",
    )

    summaries = [row.summary for row in _events(task_id=task_id)]
    assert any("引擎处理未完成" in text and "引擎崩了" in text for text in summaries)
    assert not [text for text in summaries if "翻译完成" in text]
