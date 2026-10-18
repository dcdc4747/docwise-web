"""`docx_styles`（带样式 Word 导出的纯解析层）的回归测试。

覆盖七条口径：标题级别、`px → pt`、`em` 缩进、字体族取第一个、
span 段内字号覆盖、无 style 全 `None`、脏 HTML 不抛且回退；
另加 `<li>` 前缀、`line-height`、`text-align`、`blockquote` 容器，
以及 `to_docx_bytes` 的载荷接线（有样式走 HTML、失败回退 Markdown）。

⚠️ 不用 `tmp_path`（受限环境写不了临时目录）；Word 进程用
`monkeypatch` 换成假 `subprocess.run`，只验载荷，不起解释器。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services import draft_export
from app.services.docx_styles import (
    REASON_EMPTY,
    REASON_FAILED,
    REASON_NO_BLOCKS,
    _HtmlBlockParser,
    parse_body_html,
    parse_body_html_checked,
)

# ============================================================ ① 标题级别

def test_heading_levels_are_mapped() -> None:
    blocks = parse_body_html("<h1>一级</h1><h2>二级</h2><h3>三级</h3>")

    assert [block["level"] for block in blocks] == [1, 2, 3]
    assert [block["text"] for block in blocks] == ["一级", "二级", "三级"]


def test_paragraph_is_level_zero() -> None:
    blocks = parse_body_html("<p>正文</p>")

    assert blocks[0]["level"] == 0


# ============================================================ ② px → pt

def test_px_font_size_converts_to_pt() -> None:
    block = parse_body_html('<p style="font-size: 16px">正文</p>')[0]

    assert block["font_size_pt"] == 12.0
    # 口径：pt = px * 0.75，16px 就是 12pt


def test_pt_font_size_is_kept() -> None:
    block = parse_body_html('<p style="font-size: 15pt">正文</p>')[0]

    assert block["font_size_pt"] == 15.0


# ============================================================ ③ em 缩进

def test_text_indent_em_uses_block_font_size() -> None:
    block = parse_body_html(
        '<p style="font-size: 16px; text-indent: 2em">正文</p>'
    )[0]

    # 16px → 12pt；2em = 2 × 12pt = 24pt（规则 3 的公式）
    assert block["font_size_pt"] == 12.0
    assert block["first_line_indent_pt"] == 24.0


def test_text_indent_px_converts_to_pt() -> None:
    block = parse_body_html('<p style="text-indent: 32px">正文</p>')[0]

    assert block["first_line_indent_pt"] == 24.0


# ============================================================ ④ 字体族

def test_font_family_takes_first_and_strips_quotes() -> None:
    block = parse_body_html(
        '<p style="font-family: &quot;Kaiti SC&quot;, KaiTi, serif">正文</p>'
    )[0]

    assert block["font_family"] == "Kaiti SC"


def test_font_family_keeps_unquoted_name() -> None:
    block = parse_body_html('<p style="font-family: 楷体">正文</p>')[0]

    assert block["font_family"] == "楷体"


# ============================================================ ⑤ span 覆盖

def test_span_font_size_overrides_block_size() -> None:
    block = parse_body_html(
        '<p style="font-size: 16px">前'
        '<span style="font-size: 22px">重点</span>后</p>'
    )[0]

    assert block["text"] == "前重点后"
    # 22px × 0.75 = 16.5pt，段内字号盖过块的 12pt
    assert block["font_size_pt"] == 16.5


# ============================================================ ⑥ 无 style

def test_block_without_style_has_none_fields() -> None:
    block = parse_body_html("<p>正文</p>")[0]

    assert block == {
        "text": "正文",
        "level": 0,
        "bold": False,
        "font_family": None,
        "font_size_pt": None,
        "line_height": None,
        "first_line_indent_pt": None,
        "align": None,
    }


# ============================================================ ⑦ 脏 HTML

@pytest.mark.parametrize(
    "dirty",
    [
        "",
        "   ",
        "<p></p><h1></h1>",
        "<p><h1><span>",
        '<p style="font-size: 16px>没闭合引号',
    ],
)
def test_dirty_html_returns_empty_and_never_raises(dirty: str) -> None:
    assert parse_body_html(dirty) == []


def test_angle_brackets_are_plain_text_not_a_crash() -> None:
    # `<<<>>>` 不是标签，是正文：解析成一段也算对，只要不抛。
    assert parse_body_html("<<<>>>") == [
        {
            "text": "<<<>>>",
            "level": 0,
            "bold": False,
            "font_family": None,
            "font_size_pt": None,
            "line_height": None,
            "first_line_indent_pt": None,
            "align": None,
        }
    ]


def test_none_input_is_empty_not_an_error() -> None:
    assert parse_body_html(None) == []  # type: ignore[arg-type]
    assert parse_body_html_checked(None) == ([], REASON_EMPTY)


def test_parser_exception_is_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(self: _HtmlBlockParser, data: str) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(_HtmlBlockParser, "feed", boom)

    assert parse_body_html_checked("<p>正文</p>") == ([], REASON_FAILED)


def test_checked_reports_success_and_no_blocks() -> None:
    blocks, reason = parse_body_html_checked("<p>正文</p>")
    assert blocks[0]["text"] == "正文"
    assert reason is None
    assert parse_body_html_checked("<p></p>") == ([], REASON_NO_BLOCKS)


# ============================================================ ⑧ li 前缀

def test_list_items_get_bullet_prefix() -> None:
    blocks = parse_body_html("<ul><li>条目一</li><li>条目二</li></ul>")

    assert [block["text"] for block in blocks] == ["• 条目一", "• 条目二"]
    assert [block["level"] for block in blocks] == [0, 0]


def test_paragraph_inside_list_item_is_one_block() -> None:
    blocks = parse_body_html("<ul><li><p>条目</p></li></ul>")

    assert len(blocks) == 1
    assert blocks[0]["text"] == "• 条目"


# ============================================================ ⑨ 行距

def test_line_height_is_a_multiple() -> None:
    assert (
        parse_body_html('<p style="line-height: 1.5">甲</p>')[0]["line_height"]
        == 1.5
    )
    assert (
        parse_body_html('<p style="line-height: 150%">乙</p>')[0][
            "line_height"
        ]
        == 1.5
    )


def test_line_height_px_is_relative_to_font_size() -> None:
    block = parse_body_html(
        '<p style="font-size: 16px; line-height: 24px">丙</p>'
    )[0]

    # 24px → 18pt；18 / 12 = 1.5 倍
    assert block["line_height"] == 1.5


# ============================================================ ⑩ 对齐

def test_text_align_center_passes_through() -> None:
    block = parse_body_html('<p style="text-align: center">居中</p>')[0]

    assert block["align"] == "center"


def test_unknown_align_is_none() -> None:
    block = parse_body_html('<p style="text-align: sideways">歪</p>')[0]

    assert block["align"] is None


# ============================================================ ⑪ 其他容器

def test_blockquote_keeps_its_own_style() -> None:
    blocks = parse_body_html(
        '<blockquote style="font-family: 楷体; font-size: 18px">'
        "<p>引文</p></blockquote>"
    )

    assert len(blocks) == 1
    assert blocks[0]["text"] == "引文"
    assert blocks[0]["level"] == 0
    assert blocks[0]["font_family"] == "楷体"
    assert blocks[0]["font_size_pt"] == 13.5


def test_bold_from_style_and_strong() -> None:
    assert parse_body_html('<p style="font-weight: 700">粗</p>')[0]["bold"]
    assert parse_body_html("<p><strong>粗</strong>细</p>")[0]["bold"]


# ============================================================ ⑫ 导出接线

def _capture_payload(monkeypatch: pytest.MonkeyPatch) -> dict:
    captured: dict = {}

    def fake_run(*args: object, **kwargs: object) -> SimpleNamespace:
        captured["payload"] = json.loads(kwargs["input"].decode("utf-8"))
        return SimpleNamespace(returncode=0, stdout=b"PK\x03\x04", stderr=b"")

    monkeypatch.setenv("DOCWISE_ENGINE_PYTHON", "python")
    monkeypatch.setattr(draft_export.subprocess, "run", fake_run)
    return captured


def test_docx_payload_uses_html_styles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_payload(monkeypatch)
    draft = {
        "title": "样式稿",
        "body_md": "旧正文",
        "body_html": (
            '<p style="font-family: Kaiti SC; font-size: 16px; '
            'text-indent: 2em; line-height: 1.8; text-align: center">正文</p>'
        ),
    }

    data = draft_export.to_docx_bytes(draft, [])

    assert data == b"PK\x03\x04"
    block = captured["payload"]["blocks"][0]
    assert block["kind"] == "paragraph"
    assert block["text"] == "正文"
    assert block["font_family"] == "Kaiti SC"
    assert block["font_size_pt"] == 12.0
    assert block["first_line_indent_pt"] == 24.0
    assert block["line_height"] == 1.8
    assert block["align"] == "center"


def test_docx_payload_falls_back_when_html_is_dirty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_payload(monkeypatch)
    draft = {
        "title": "脏稿",
        "body_md": "# 标题\n\n正文",
        "body_html": "<p></p><h1></h1>",
    }

    data = draft_export.to_docx_bytes(draft, [])

    assert data == b"PK\x03\x04"
    blocks = captured["payload"]["blocks"]
    assert [block["kind"] for block in blocks] == ["heading", "paragraph"]
    assert [block["text"] for block in blocks] == ["标题", "正文"]


def test_docx_payload_falls_back_without_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_payload(monkeypatch)
    draft = {"title": "老稿", "body_md": "只有 Markdown", "body_html": None}

    assert draft_export.to_docx_bytes(draft, []) == b"PK\x03\x04"
    blocks = captured["payload"]["blocks"]
    assert blocks == [{"kind": "paragraph", "text": "只有 Markdown"}]
