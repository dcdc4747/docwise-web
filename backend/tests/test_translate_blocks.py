"""逐段翻译的纯函数单测（不发网络请求）。

翻译这条路的失败模式是**错位**：把 A 段的译文贴到 B 段上——比漏译更糟，
因为读者看不出来。所以"编号对回"必须锁死：只认自己发出去的编号，
模型多给的、编出来的、空的，一律丢掉。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader, f"加载不了脚本：{name}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_module_imports_without_third_party() -> None:
    module = _load("translate_blocks")
    assert callable(module.translate_blocks)
    assert callable(module.parse_translations)


def test_build_messages_keeps_every_index_and_target_lang() -> None:
    module = _load("translate_blocks")
    batch = [(3, "Third paragraph."), (4, "Fourth paragraph.")]

    messages = module.build_messages(batch, "中文")

    assert messages[0]["role"] == "system"
    user = messages[1]["content"]
    assert "中文" in user
    assert "[3] Third paragraph." in user
    assert "[4] Fourth paragraph." in user


def test_build_messages_clips_overlong_paragraph() -> None:
    module = _load("translate_blocks")
    long_text = "x" * (module.MAX_CHARS + 500)

    user = module.build_messages([(0, long_text)], "中文")[1]["content"]

    assert "x" * module.MAX_CHARS in user
    assert "x" * (module.MAX_CHARS + 1) not in user


def test_parse_translations_plain_array() -> None:
    module = _load("translate_blocks")
    raw = '[{"i": 0, "t": "第一段"}, {"i": 1, "t": "第二段"}]'

    assert module.parse_translations(raw, [0, 1]) == {0: "第一段", 1: "第二段"}


def test_parse_translations_tolerates_code_fence_and_wrapper() -> None:
    module = _load("translate_blocks")
    fenced = '```json\n[{"i": 2, "t": "甲"}]\n```'
    wrapped = '{"translations": [{"index": 2, "text": "甲"}]}'

    assert module.parse_translations(fenced, [2]) == {2: "甲"}
    assert module.parse_translations(wrapped, [2]) == {2: "甲"}


def test_parse_translations_drops_unknown_and_empty() -> None:
    """只认发出去的编号：模型多给的、空的、编号编出来的，全丢。"""
    module = _load("translate_blocks")
    raw = (
        '[{"i": 0, "t": "要的"},'
        ' {"i": 99, "t": "编出来的编号"},'
        ' {"i": 1, "t": "   "},'
        ' {"i": "x", "t": "编号不是数字"},'
        ' "不是对象"]'
    )

    assert module.parse_translations(raw, [0, 1]) == {0: "要的"}


def test_parse_translations_garbage_returns_empty() -> None:
    module = _load("translate_blocks")

    assert module.parse_translations("模型今天不想输出 JSON", [0]) == {}
    assert module.parse_translations("", [0]) == {}


def test_translate_blocks_without_api_key_reports_reason(monkeypatch) -> None:
    """没配 key：如实说清楚，不发请求、不编译文。"""
    module = _load("translate_blocks")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    blocks = [{"block_id": "p0_b0", "text": "Abstract", "translated": None}]

    done, problems = module.translate_blocks(
        blocks, source_lang="en", target_lang="zh"
    )

    assert done == 0
    assert problems and "DEEPSEEK_API_KEY" in problems[0]
    assert blocks[0]["translated"] is None
