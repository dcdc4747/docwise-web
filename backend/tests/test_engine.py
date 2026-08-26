from pathlib import Path

import pytest

from app.engine import (
    BlockStatus,
    TranslateRequest,
    TranslationEngine,
    TranslationResult,
    get_engine,
)


def test_get_engine_default_is_pdf2zh() -> None:
    engine = get_engine()
    assert isinstance(engine, TranslationEngine)
    assert engine.name == "pdf2zh"


def test_get_engine_unknown_raises() -> None:
    with pytest.raises(ValueError):
        get_engine("not-a-real-engine")


def test_translate_request_defaults() -> None:
    req = TranslateRequest(source_path=Path("/tmp/a.pdf"))
    assert req.source_lang == "en"
    assert req.target_lang == "zh"
    assert req.tier == "fast"


def test_block_status_visible() -> None:
    block = BlockStatus(
        block_id="b1", text="hello", status="success", translated="你好"
    )
    assert block.status == "success"
    assert block.translated == "你好"


def test_result_initial_state() -> None:
    res = TranslationResult(task_id="t1", translated_path=None)
    assert res.status == "pending"
    assert res.progress == 0.0
    assert res.blocks == []
