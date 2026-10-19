"""版式工具包（`app/agent/packs/format.py`）的用例。

盯这几件事：

1. 包里**恰好 2 个工具**（场景工具预算是 15，写作侧只留得出 2 格）；
2. `apply_style` 单段只改那一段，anchor 找不到**一行都不写**；
3. 整篇 / 体例 / dry_run / 版本快照各按约定走；
4. `preview_styles` 只读、最多 40 块；
5. 别人的草稿当"找不到"。

⚠️ 不用 `tmp_path`（AGENTS.md：受限环境不可写）；数据自己建、自己清。
"""

from __future__ import annotations

import inspect

from helpers import TEST_USER_ID
from sqlalchemy import delete, select

from app.agent.contracts import ToolContext
from app.agent.packs import format as format_pack
from app.db import SessionLocal
from app.models import Draft, DraftVersion


def _ctx(
    user_id: int = TEST_USER_ID, draft_id: int | None = None
) -> ToolContext:
    scope: dict = {"draft_id": draft_id} if draft_id is not None else {}
    return ToolContext(
        db=None,
        user_id=user_id,
        scene_id="write_compose",
        scope=scope,
    )


def _make_draft(
    *,
    body_html: str | None,
    body_md: str = "正文",
    title: str = "版式测试稿",
    user_id: int = TEST_USER_ID,
) -> int:
    with SessionLocal() as session:
        row = Draft(
            user_id=user_id,
            title=title,
            body_md=body_md,
            body_html=body_html,
        )
        session.add(row)
        session.commit()
        return row.id


def _html(draft_id: int) -> str | None:
    with SessionLocal() as session:
        row = session.get(Draft, draft_id)
        return None if row is None else row.body_html


def _md(draft_id: int) -> str:
    with SessionLocal() as session:
        row = session.get(Draft, draft_id)
        return "" if row is None else (row.body_md or "")


def _versions(draft_id: int) -> list[dict]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(DraftVersion)
            .where(DraftVersion.draft_id == draft_id)
            .order_by(DraftVersion.id)
        ).all()
        return [
            {
                "id": row.id,
                "body_md": row.body_md,
                "body_html": row.body_html,
                "title": row.title,
                "source": row.source,
                "note": row.note,
            }
            for row in rows
        ]


def _drop(*draft_ids: int) -> None:
    if not draft_ids:
        return
    with SessionLocal() as session:
        session.execute(
            delete(DraftVersion).where(DraftVersion.draft_id.in_(draft_ids))
        )
        session.execute(delete(Draft).where(Draft.id.in_(draft_ids)))
        session.commit()


# ============================================================ ① 包契约


def test_pack_has_exactly_two_tools() -> None:
    assert format_pack.PACK.name == "format"
    names = [spec.name for spec in format_pack.PACK.tools]
    assert names == ["preview_styles", "apply_style"], (
        "场景工具预算只有 2 格，别再加工具"
    )
    for spec in format_pack.PACK.tools:
        assert spec.parameters["type"] == "object"
        params = list(inspect.signature(spec.handler).parameters)
        assert params == ["ctx", "args"], f"{spec.name} 的 handler 签名不对"


# ============================================================ ② 单段命中


def test_apply_style_paragraph_changes_only_that_block() -> None:
    html = (
        "<p>第一段 手性可以分成两部分</p>"
        "<p>第二段 讲别的事</p>"
        "<h2>标题</h2>"
    )
    draft_id = _make_draft(body_html=html, body_md="第一段\n\n第二段")

    result = format_pack.apply_style(
        _ctx(),
        {
            "draft_id": draft_id,
            "scope": "paragraph",
            "anchor": "手性可以分成",
            "style": {
                "fontFamily": "宋体",
                "fontSize": "16px",
                "lineHeight": "1.8",
            },
        },
    )

    assert result.data["changed"] == 1
    assert result.data["changed_blocks"] == [0]
    assert result.data["version"] is not None
    stored = _html(draft_id) or ""
    assert stored.startswith(
        '<p style="font-family: 宋体; font-size: 16px; line-height: 1.8">'
    )
    assert "手性可以分成两部分" in stored
    # 别的块一个字节都不许动
    assert "<p>第二段 讲别的事</p>" in stored
    assert "<h2>标题</h2>" in stored
    assert stored.count("font-size") == 1
    assert "宋体" in result.note and "16px" in result.note
    _drop(draft_id)


# ============================================================ ③ 锚点对不上


def test_apply_style_missing_anchor_writes_nothing() -> None:
    html = "<p>手性可以分成两部分</p><p>第二段</p>"
    draft_id = _make_draft(body_html=html)

    result = format_pack.apply_style(
        _ctx(),
        {
            "draft_id": draft_id,
            "scope": "paragraph",
            "anchor": "手性可以割成",
            "style": {"fontSize": "20px"},
        },
    )

    assert "稿子里没有这段文字，别硬改" in result.note
    assert _html(draft_id) == html, "找不到锚点就不许改库"
    assert _versions(draft_id) == []
    _drop(draft_id)


# ============================================================ ④ 版本快照


def test_apply_style_records_previous_html_before_write() -> None:
    html = "<p>第一段</p><p>第二段</p>"
    draft_id = _make_draft(
        body_html=html, body_md="第一段\n\n第二段", title="版本测试"
    )

    result = format_pack.apply_style(
        _ctx(),
        {
            "draft_id": draft_id,
            "scope": "document",
            "style": {"fontSize": "16px"},
        },
    )

    versions = _versions(draft_id)
    assert len(versions) == 1
    version = versions[0]
    assert version["source"] == "ai"
    assert version["note"] == "AI 改版式"
    assert version["body_html"] == html, "版本里必须是改前的 HTML"
    assert version["body_md"] == "第一段\n\n第二段"
    assert version["title"] == "版本测试"
    assert result.data["version"] == version["id"]
    assert _html(draft_id) != html
    _drop(draft_id)


# ============================================================ ⑤ 整篇


def test_apply_style_document_changes_every_block() -> None:
    html = "<p>甲</p><p>乙</p><h2>丙</h2>"
    draft_id = _make_draft(body_html=html, body_md="甲\n\n乙\n\n## 丙")

    result = format_pack.apply_style(
        _ctx(),
        {
            "draft_id": draft_id,
            "scope": "document",
            "style": {"fontSize": "16px", "paragraphSpacing": "10px"},
        },
    )

    assert result.data["changed"] == 3
    stored = _html(draft_id) or ""
    assert stored.count("font-size: 16px") == 3
    assert stored.count("margin-bottom: 10px") == 3
    assert _md(draft_id) == "甲\n\n乙\n\n## 丙", (
        "body_md 是派生视图，别在这儿改"
    )
    _drop(draft_id)


# ============================================================ ⑥ 体例


def test_apply_style_templates_and_unknown_template() -> None:
    cases = {
        "cn-journal": (
            "font-family: 宋体",
            "font-size: 16px",
            "line-height: 1.8",
            "text-indent: 2em",
        ),
        "apa": (
            "font-family: Times New Roman",
            "font-size: 16px",
            "line-height: 2.0",
            "text-indent: 0",
        ),
        "ieee": (
            "font-family: Times New Roman",
            "font-size: 13px",
            "line-height: 1.4",
        ),
    }
    draft_ids: list[int] = []
    for template, expected in cases.items():
        draft_id = _make_draft(body_html="<p>一段正文</p>")
        draft_ids.append(draft_id)
        result = format_pack.apply_style(
            _ctx(),
            {
                "draft_id": draft_id,
                "scope": "document",
                "template": template,
            },
        )
        assert result.data["changed"] == 1
        stored = _html(draft_id) or ""
        for piece in expected:
            assert piece in stored, f"{template} 少了 {piece}：{stored}"
        assert template in result.note
    # ieee 没有缩进这条默认值
    assert "text-indent" not in (_html(draft_ids[2]) or "")

    before = _html(draft_ids[0])
    unknown = format_pack.apply_style(
        _ctx(),
        {
            "draft_id": draft_ids[0],
            "scope": "document",
            "template": "gb-t-7714",
        },
    )
    assert "cn-journal" in unknown.note
    assert "apa" in unknown.note and "ieee" in unknown.note
    assert _html(draft_ids[0]) == before, "未知体例不许改库"
    assert len(_versions(draft_ids[0])) == 1, "未知体例不该再存一版"
    _drop(*draft_ids)


# ============================================================ ⑦ 只看不改


def test_apply_style_dry_run_writes_nothing() -> None:
    html = "<p>甲</p><p>乙</p>"
    draft_id = _make_draft(body_html=html)

    result = format_pack.apply_style(
        _ctx(),
        {
            "draft_id": draft_id,
            "scope": "document",
            "style": {"fontSize": "18px"},
            "dry_run": True,
        },
    )

    assert result.data["dry_run"] is True
    assert result.data["changed"] == 2
    assert result.data["version"] is None
    assert _html(draft_id) == html
    assert _versions(draft_id) == []
    assert "预览" in result.note and "18px" in result.note
    preview = result.data["preview"]
    assert preview[0]["fontSize"] == "18px", "dry_run 要给出会改成什么样"
    _drop(draft_id)


# ============================================================ ⑧ 预览


def test_preview_styles_is_read_only_and_caps_at_40() -> None:
    html = "".join(f"<p>第{i}段的内容</p>" for i in range(45))
    draft_id = _make_draft(body_html=html)

    result = format_pack.preview_styles(_ctx(), {"draft_id": draft_id})

    assert len(result.data) == 40
    assert "45" in result.note and "40" in result.note
    assert result.data[0]["index"] == 0
    assert result.data[0]["text"] == "第0段的内容"
    assert _html(draft_id) == html, "预览是只读的"
    assert _versions(draft_id) == []
    _drop(draft_id)


def test_preview_styles_reports_inherited_font() -> None:
    html = (
        '<blockquote style="font-family: 楷体; font-size: 18px">'
        "<p>引文</p></blockquote>"
    )
    draft_id = _make_draft(body_html=html)

    result = format_pack.preview_styles(_ctx(), {"draft_id": draft_id})

    assert len(result.data) == 1
    item = result.data[0]
    assert item["fontFamily"] == "楷体"
    assert item["fontSize"] == "18px"
    assert item["style"] == "", "自己身上没有 style，值是从祖先算来的"
    _drop(draft_id)


# ============================================================ ⑨ 归属


def test_other_users_draft_is_treated_as_missing() -> None:
    html = "<p>别人的稿子</p>"
    draft_id = _make_draft(body_html=html, user_id=TEST_USER_ID + 999)

    preview = format_pack.preview_styles(_ctx(), {"draft_id": draft_id})
    assert "找不到" in preview.note
    assert preview.data == []

    paragraph = format_pack.apply_style(
        _ctx(),
        {
            "draft_id": draft_id,
            "scope": "paragraph",
            "anchor": "别人的稿子",
            "style": {"fontSize": "16px"},
        },
    )
    document = format_pack.apply_style(
        _ctx(),
        {
            "draft_id": draft_id,
            "scope": "document",
            "style": {"fontSize": "16px"},
        },
    )

    assert "找不到" in paragraph.note
    assert "找不到" in document.note
    assert _html(draft_id) == html
    assert _versions(draft_id) == []
    _drop(draft_id)


# ============================================================ ⑩ 加粗与合并


def test_bold_wraps_text_and_keeps_inner_markup() -> None:
    html = (
        '<p style="color: red; font-size: 12px">前文'
        '<span style="color: blue">重点</span>后文</p>'
    )
    draft_id = _make_draft(body_html=html)

    format_pack.apply_style(
        _ctx(),
        {
            "draft_id": draft_id,
            "scope": "paragraph",
            "anchor": "重点",
            "style": {"bold": True, "fontSize": "16px"},
        },
    )

    stored = _html(draft_id) or ""
    assert stored.count("<strong>") == 1
    assert stored.count("</strong>") == 1
    assert '<span style="color: blue">重点</span>' in stored
    assert "color: red" in stored, "已有 style 要保留"
    assert "font-size: 16px" in stored
    assert "font-size: 12px" not in stored, "同名要覆盖"
    _drop(draft_id)


# ============================================================ ⑪ 参数校验


def test_apply_style_rejects_bad_arguments_without_writing() -> None:
    html = "<p>正文</p>"
    draft_id = _make_draft(body_html=html)

    bad_scope = format_pack.apply_style(
        _ctx(),
        {
            "draft_id": draft_id,
            "scope": "section",
            "style": {"fontSize": "16px"},
        },
    )
    assert "paragraph" in bad_scope.note and "document" in bad_scope.note

    no_anchor = format_pack.apply_style(
        _ctx(),
        {
            "draft_id": draft_id,
            "scope": "paragraph",
            "style": {"fontSize": "16px"},
        },
    )
    assert "anchor" in no_anchor.note

    nothing = format_pack.apply_style(
        _ctx(), {"draft_id": draft_id, "scope": "document"}
    )
    assert "style" in nothing.note

    assert _html(draft_id) == html
    assert _versions(draft_id) == []
    _drop(draft_id)


# ============================================================ ⑫ 老稿子（无 HTML）


def test_apply_style_on_draft_without_html_writes_nothing() -> None:
    draft_id = _make_draft(body_html=None, body_md="只有 md 的老稿子")

    result = format_pack.apply_style(
        _ctx(),
        {
            "draft_id": draft_id,
            "scope": "document",
            "style": {"fontSize": "16px"},
        },
    )

    assert "body_html" in result.note
    assert _html(draft_id) is None, "没有富文本正文就别凭空造一份"
    assert _versions(draft_id) == []

    preview = format_pack.preview_styles(_ctx(), {"draft_id": draft_id})
    assert preview.data == []
    assert "body_html" in preview.note
    _drop(draft_id)


# ============================================================ ⑬ 重复套同一套


def test_reapplying_same_style_is_a_noop() -> None:
    draft_id = _make_draft(body_html="<p>正文</p>")
    args = {
        "draft_id": draft_id,
        "scope": "document",
        "style": {"fontSize": "16px"},
    }

    first = format_pack.apply_style(_ctx(), dict(args))
    assert first.data["changed"] == 1
    before = _html(draft_id)

    second = format_pack.apply_style(_ctx(), dict(args))
    assert second.data["changed"] == 0
    assert second.data["version"] is None, "没改动就不该再存一版"
    assert _html(draft_id) == before
    assert len(_versions(draft_id)) == 1
    _drop(draft_id)
