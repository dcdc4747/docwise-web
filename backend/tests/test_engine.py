import json
import sys
from pathlib import Path

import pytest

from app.engine import (
    BlockState,
    BlockStatus,
    MediumEngine,
    OpenSourceEngine,
    TaskState,
    Tier,
    TranslateRequest,
    TranslationEngine,
    TranslationResult,
    get_engine,
)


def test_engine_child_env_gets_sanitized_no_proxy(monkeypatch) -> None:
    """引擎子进程那份环境也要洗过（实现在 `app/netenv.py`）。

    纯函数测试在 `test_netenv.py`；这里只钉"接线接对了"：
    起子进程前确实调了 `sanitize_proxy_env(child_env)`。
    """
    from app import storage
    from app.engine import open_source

    seen: list[dict] = []

    def fake_popen(cmd, env=None, **kwargs):  # noqa: ANN001, ANN003
        seen.append(dict(env or {}))
        raise RuntimeError("到此为止：只验环境，不真起引擎")

    monkeypatch.setattr(open_source.subprocess, "Popen", fake_popen)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost,::1,[::1]")
    engine = OpenSourceEngine()
    engine._env = lambda key: {"PYTHON": "python", "SCRIPT": "s.py"}.get(key)  # type: ignore[method-assign]
    # 用 storage 的临时产物目录（conftest 已把它指到系统临时区），别往仓库里写日志
    out_dir = storage.OUTPUTS_DIR / "engine-env-test"
    out_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(RuntimeError):
        engine._run_engine_command(["python", "s.py"], out_dir, None)

    assert seen and "[::1]" not in seen[0]["NO_PROXY"]
    assert seen[0]["NO_PROXY"].endswith("::1")


def test_get_engine_default_is_open_source() -> None:
    engine = get_engine()
    assert isinstance(engine, TranslationEngine)
    assert engine.name == "open-source"


def test_get_engine_unknown_raises() -> None:
    with pytest.raises(ValueError):
        get_engine("not-a-real-engine")


def test_get_engine_medium_tier() -> None:
    assert get_engine(Tier.MEDIUM).name == "medium-engine"


def test_get_engine_medium_by_string() -> None:
    assert get_engine("medium").name == "medium-engine"


def test_get_engine_precise_falls_back_to_medium() -> None:
    assert get_engine(Tier.PRECISE).name == "medium-engine"


def test_translate_request_defaults() -> None:
    req = TranslateRequest(source_path=Path("/tmp/a.pdf"))
    assert req.source_lang == "en"
    assert req.target_lang == "zh"
    assert req.tier == Tier.FAST


def test_block_status_visible() -> None:
    block = BlockStatus(
        block_id="b1", text="hello", status=BlockState.SUCCESS, translated="你好"
    )
    assert block.status == BlockState.SUCCESS
    assert block.translated == "你好"


def test_result_initial_state() -> None:
    res = TranslationResult(task_id="t1", translated_path=None)
    assert res.status == TaskState.PENDING
    assert res.progress == 0.0
    assert res.blocks == []


def test_medium_engine_unconfigured_fails_gracefully(monkeypatch) -> None:
    monkeypatch.delenv("DOCWISE_ENGINE_PYTHON", raising=False)
    monkeypatch.delenv("DOCWISE_ENGINE_SCRIPT", raising=False)
    monkeypatch.delenv("DOCWISE_ENGINE_SERVICE", raising=False)
    engine = MediumEngine()
    result = engine.translate(TranslateRequest(source_path=Path("/tmp/a.pdf")))
    assert result.status == TaskState.FAILED
    assert result.translated_path is None
    assert "DOCWISE_ENGINE" in (result.error or "")


def test_medium_engine_runs_runner_script(monkeypatch, tmp_path) -> None:
    runner = tmp_path / "runner.py"
    runner.write_text(
        "import argparse, json, pathlib\n"
        "p = argparse.ArgumentParser()\n"
        "for name in ('input', 'output', 'lang-in', 'lang-out', 'service', 'thread'):\n"
        "    p.add_argument('--' + name)\n"
        "args = p.parse_args()\n"
        "out = pathlib.Path(args.output)\n"
        "(out / 'mono.pdf').write_bytes(b'pdf')\n"
        "(out / 'dual.pdf').write_bytes(b'pdf')\n"
        "(out / 'result.json').write_text(json.dumps({\n"
        "    'status': 'completed',\n"
        "    'mono': str(out / 'mono.pdf'),\n"
        "    'dual': str(out / 'dual.pdf'),\n"
        "    'blocks': [{'block_id': 'b1', 'text': 'hello'}],\n"
        "}), encoding='utf-8')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DOCWISE_ENGINE_PYTHON", sys.executable)
    monkeypatch.setenv("DOCWISE_ENGINE_SCRIPT", str(runner))
    monkeypatch.setenv("DOCWISE_ENGINE_SERVICE", "demo")

    engine = MediumEngine()
    result = engine.translate(TranslateRequest(source_path=tmp_path / "a.pdf"))

    assert result.status == TaskState.COMPLETED
    assert result.progress == 1.0
    assert result.translated_path is not None
    assert result.translated_path.name == "mono.pdf"
    assert len(result.blocks) == 1
    assert result.blocks[0].status == BlockState.SUCCESS


def _write_runner(tmp_path: Path, *, ok: bool = True) -> str:
    """写一个假引擎包装脚本；ok=True 返回可完成的，否则返回会崩的。"""
    runner = tmp_path / f"runner_{'ok' if ok else 'bad'}.py"
    if ok:
        body = (
            "import argparse, json, pathlib\n"
            "p = argparse.ArgumentParser()\n"
            "for name in ('input', 'output', 'lang-in', 'lang-out',\n"
            " 'service', 'thread'):\n"
            "    p.add_argument('--' + name)\n"
            "args = p.parse_args()\n"
            "out = pathlib.Path(args.output)\n"
            "(out / 'mono.pdf').write_bytes(b'pdf')\n"
            "(out / 'dual.pdf').write_bytes(b'pdf')\n"
            "(out / 'result.json').write_text(json.dumps({\n"
            "    'status': 'completed',\n"
            "    'mono': str(out / 'mono.pdf'),\n"
            "    'dual': str(out / 'dual.pdf'),\n"
            "    'blocks': [{'block_id': 'b1', 'text': 'hello'}],\n"
            "}), encoding='utf-8')\n"
        )
    else:
        body = "raise SystemExit(1)\n"
    runner.write_text(body, encoding="utf-8")
    return str(runner)


def test_medium_engine_prefers_medium_env(monkeypatch, tmp_path) -> None:
    # 中档专属变量优先：即便基础变量指向坏脚本，也用中档专属的
    good = _write_runner(tmp_path, ok=True)
    bad = _write_runner(tmp_path, ok=False)
    monkeypatch.setenv("DOCWISE_ENGINE_PYTHON", sys.executable)
    monkeypatch.setenv("DOCWISE_ENGINE_SCRIPT", bad)
    monkeypatch.setenv("DOCWISE_ENGINE_SERVICE", "demo")
    monkeypatch.setenv("DOCWISE_ENGINE_MEDIUM_SCRIPT", good)

    result = MediumEngine().translate(TranslateRequest(source_path=tmp_path / "a.pdf"))

    assert result.status == TaskState.COMPLETED


def test_fast_engine_uses_base_env_only(monkeypatch, tmp_path) -> None:
    # 快档只用基础变量，中档专属变量不应影响快档
    good = _write_runner(tmp_path, ok=True)
    bad = _write_runner(tmp_path, ok=False)
    monkeypatch.setenv("DOCWISE_ENGINE_PYTHON", sys.executable)
    monkeypatch.setenv("DOCWISE_ENGINE_SCRIPT", good)
    monkeypatch.setenv("DOCWISE_ENGINE_SERVICE", "demo")
    monkeypatch.setenv("DOCWISE_ENGINE_MEDIUM_SCRIPT", bad)

    result = OpenSourceEngine().translate(
        TranslateRequest(source_path=tmp_path / "a.pdf")
    )

    assert result.status == TaskState.COMPLETED


# ---------- 文档结构（M6 / C1）：引擎侧给什么、后端就存什么 ----------


def _run_fake_engine_with_payload(monkeypatch, payload: dict) -> TranslationResult:
    """起一个假引擎（只写 result.json），验证"引擎 → TranslationResult"这条接线。

    产物目录用 `storage.OUTPUTS_DIR`（conftest 已指到临时区），不往仓库里写。
    """
    from uuid import uuid4

    from app import storage

    workdir = storage.OUTPUTS_DIR / f"structure_{uuid4().hex}"
    workdir.mkdir(parents=True, exist_ok=True)
    payload_file = workdir / "payload.json"
    payload_file.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    runner = workdir / "runner.py"
    runner.write_text(
        "import argparse, json, pathlib\n"
        "p = argparse.ArgumentParser()\n"
        "for name in ('input', 'output', 'lang-in', 'lang-out', 'service', 'thread'):\n"
        "    p.add_argument('--' + name)\n"
        "args = p.parse_args()\n"
        "out = pathlib.Path(args.output)\n"
        "(out / 'mono.pdf').write_bytes(b'pdf')\n"
        "(out / 'dual.pdf').write_bytes(b'pdf')\n"
        f"payload = json.loads(pathlib.Path({str(payload_file)!r})"
        ".read_text(encoding='utf-8'))\n"
        "payload['mono'] = str(out / 'mono.pdf')\n"
        "payload['dual'] = str(out / 'dual.pdf')\n"
        "(out / 'result.json').write_text(json.dumps(payload), encoding='utf-8')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DOCWISE_ENGINE_PYTHON", sys.executable)
    monkeypatch.setenv("DOCWISE_ENGINE_SCRIPT", str(runner))
    monkeypatch.setenv("DOCWISE_ENGINE_SERVICE", "demo")

    return OpenSourceEngine().translate(
        TranslateRequest(source_path=workdir / "a.pdf", output_dir=workdir / "out")
    )


def _completed_payload(**extra) -> dict:
    payload = {
        "status": "completed",
        "blocks": [{"block_id": "b1", "text": "hello"}],
    }
    payload.update(extra)
    return payload


def test_engine_reads_structure_from_result_json(monkeypatch) -> None:
    """引擎给了 structure：原样带回来，后端不加判定、不重算层级。"""
    structure = {
        "headings": [{"block_id": "p1_b5", "level": 2, "text": "2.1. 技术接受模型"}],
        "references": {
            "count": 1,
            "entries": [{"index": 1, "text": "F. Hund, Z. Phys. 43, 805 (1927)."}],
        },
    }

    result = _run_fake_engine_with_payload(
        monkeypatch, _completed_payload(structure=structure)
    )

    assert result.status == TaskState.COMPLETED
    assert result.structure == structure


def test_engine_without_structure_is_none(monkeypatch) -> None:
    """老产物 / 引擎那条路还没接上：structure 是 None，**不抛异常、不补默认值**。"""
    result = _run_fake_engine_with_payload(monkeypatch, _completed_payload())

    assert result.status == TaskState.COMPLETED
    assert result.structure is None


@pytest.mark.parametrize("bad", [[1, 2], "headings", 42, None, True])
def test_engine_structure_wrong_type_is_none(monkeypatch, bad) -> None:
    """形状不对（不是对象）就当没有——坏数据不许把任务搞失败。"""
    result = _run_fake_engine_with_payload(
        monkeypatch, _completed_payload(structure=bad)
    )

    assert result.status == TaskState.COMPLETED
    assert result.structure is None


def test_worker_persists_structure_to_task_row() -> None:
    """C1 判据①：结构结果落到库里。

    worker 把引擎给的 structure **原样**写进 `tasks.structure`。
    """
    from helpers import TEST_USER_ID

    from app.db import SessionLocal
    from app.models import Task
    from app.worker import TaskEventBus, TranslationWorker

    structure = {
        "headings": [{"block_id": "b1", "level": 1, "text": "Introduction"}],
        "references": {"count": 2, "entries": [{"index": 1, "text": "ref one"}]},
    }

    with SessionLocal() as session:
        task = Task(filename="a.pdf", user_id=TEST_USER_ID, status="in_progress")
        session.add(task)
        session.commit()
        task_id = task.id

    worker = TranslationWorker(TaskEventBus())
    worker._persist_result(
        task_id,
        TranslationResult(
            task_id=str(task_id),
            translated_path=None,
            status=TaskState.COMPLETED,
            progress=1.0,
            structure=structure,
        ),
    )

    with SessionLocal() as session:
        saved = session.get(Task, task_id)
        assert saved is not None
        assert saved.structure == structure
        assert saved.status == TaskState.COMPLETED.value

