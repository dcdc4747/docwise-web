from __future__ import annotations

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.engine import BlockState
from app.main import app
from app.models import Task, TaskBlock

FAKE_ANSWER = {"answer": "实验方法使用卷积神经网络。", "source_block_ids": ["b1"]}

B1 = "我们的实验方法使用卷积神经网络进行图像分类。"
B2 = "结论是模型精度达到百分之九十九。"


def _make_task_with_blocks(translated: list[str]) -> int:
    with SessionLocal() as session:
        task = Task(filename="a.pdf", status="completed")
        session.add(task)
        session.flush()
        for idx, text in enumerate(translated, start=1):
            session.add(
                TaskBlock(
                    task_id=task.id,
                    block_id=f"b{idx}",
                    text="orig",
                    status=BlockState.SUCCESS,
                    translated=text,
                )
            )
        session.commit()
        return task.id


def test_ask_full_context_short_text(monkeypatch) -> None:
    calls: list = []

    def fake(items, question) -> dict:
        calls.append((items, question))
        return FAKE_ANSWER

    monkeypatch.setattr("app.routers.ask.answer_question", fake)
    with TestClient(app) as client:
        task_id = _make_task_with_blocks([B1])
        res = client.post(f"/api/tasks/{task_id}/ask", json={"question": "实验方法？"})

    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "full_context"
    assert data["answer"] == FAKE_ANSWER["answer"]
    assert data["source_block_ids"] == ["b1"]
    assert len(calls) == 1
    assert calls[0][0] == [("b1", B1)]  # 全量入上下文：整篇都给了 LLM


def test_ask_fts_when_over_threshold(monkeypatch) -> None:
    calls: list = []

    def fake(items, question) -> dict:
        calls.append(items)
        return FAKE_ANSWER

    monkeypatch.setattr("app.routers.ask.answer_question", fake)
    monkeypatch.setattr(
        "app.routers.ask.settings.docwise_ask_full_context_max_chars", 10
    )
    with TestClient(app) as client:
        task_id = _make_task_with_blocks([B1, B2])
        res = client.post(
            f"/api/tasks/{task_id}/ask", json={"question": "实验方法是什么"}
        )

    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "fts"
    assert data["answer"] == FAKE_ANSWER["answer"]
    assert len(calls) == 1
    assert calls[0][0] == ("b1", B1)  # FTS 只召回支撑答案的块，未把无关块塞给 LLM


def test_ask_fts_no_hits_honest(monkeypatch) -> None:
    calls: list = []

    def fake(items, question) -> dict:
        calls.append(items)
        return FAKE_ANSWER

    monkeypatch.setattr("app.routers.ask.answer_question", fake)
    monkeypatch.setattr(
        "app.routers.ask.settings.docwise_ask_full_context_max_chars", 10
    )
    with TestClient(app) as client:
        task_id = _make_task_with_blocks([B1, B2])
        res = client.post(f"/api/tasks/{task_id}/ask", json={"question": "zzqqxx"})

    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "fts"
    assert data["source_block_ids"] == []
    assert "没有找到" in data["answer"]  # 诚实兜底
    assert len(calls) == 0  # 召不回就不调 LLM，不编造


def test_ask_empty_question_400(monkeypatch) -> None:
    monkeypatch.setattr("app.routers.ask.answer_question", lambda items, q: FAKE_ANSWER)
    with TestClient(app) as client:
        task_id = _make_task_with_blocks([B1])
        res = client.post(f"/api/tasks/{task_id}/ask", json={"question": "   "})

    assert res.status_code == 400


def test_ask_task_without_blocks_400(monkeypatch) -> None:
    monkeypatch.setattr("app.routers.ask.answer_question", lambda items, q: FAKE_ANSWER)
    with TestClient(app) as client:
        with SessionLocal() as session:
            task = Task(filename="a.pdf", status="completed")
            session.add(task)
            session.commit()
            task_id = task.id
        res = client.post(f"/api/tasks/{task_id}/ask", json={"question": "hi"})

    assert res.status_code == 400


def test_ask_missing_task_404() -> None:
    with TestClient(app) as client:
        res = client.post("/api/tasks/9999/ask", json={"question": "hi"})

    assert res.status_code == 404
