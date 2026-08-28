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
