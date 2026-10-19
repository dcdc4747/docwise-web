"""版式工具包（format）：让写作侧能真的改稿子的版式。

两个工具，一个看、一个改：

- `preview_styles`：只读，列出每段的前 20 字与**实际**字号/字体；
- `apply_style`：一个入口管三件事——单段（`scope="paragraph"`）、
  整篇（`scope="document"`）、按体例套默认值（`template`）。

怎么落地：改 `body_html` 里每个块（`p` / `h1`–`h3` / `li` /
`blockquote`）的 `style="..."`——已有声明保留，同名覆盖；
`bold` 用 `<strong>` 包住块内文本，块内已有的 `<span style>` 结构不动。

三条口径：

- 只改**当前用户**的草稿（别人的当"找不到"）；
- 真改之前先存一版 `DraftVersion(source="ai")`——这是撤销的前提；
- `body_md` 一个字不动：它是 `body_html` 的派生视图，转换在前端做，
  这里再实现一套 md 转换就会变成第二个真源。

⚠️ 这个文件**不许 import pydantic_ai**（结构用例钉着）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from typing import Any

from sqlalchemy import delete, select

from ...db import SessionLocal
from ...models import Draft, DraftVersion
from ..contracts import Pack, ToolContext, ToolResult, ToolSpec

# 能当"一段"的块元素：TipTap 的正文就是这几种交替出现
_BLOCK_TAGS = frozenset({"p", "h1", "h2", "h3", "li", "blockquote"})
_VOID_TAGS = frozenset(
    {"br", "img", "hr", "input", "meta", "link", "col", "area", "embed",
     "source", "track", "wbr"}
)

# 样式键 → CSS 属性名。`bold` 不是 CSS，它走 <strong>
_CSS_MAP = {
    "fontFamily": "font-family",
    "fontSize": "font-size",
    "lineHeight": "line-height",
    "textIndent": "text-indent",
    "textAlign": "text-align",
    "paragraphSpacing": "margin-bottom",
}

# 数值型键没带单位时补 px（`lineHeight` 是无单位倍数，不补）
_PX_KEYS = frozenset({"fontSize", "textIndent", "paragraphSpacing"})
_ALIGN_VALUES = ("left", "center", "right")
_ALIGN_LABELS = {"left": "左对齐", "center": "居中", "right": "右对齐"}

# 体例默认值；`style` 里的键会覆盖这里的同名项
_TEMPLATES: dict[str, dict[str, Any]] = {
    "cn-journal": {
        "fontFamily": "宋体",
        "fontSize": "16px",
        "lineHeight": "1.8",
        "textIndent": "2em",
    },
    "apa": {
        "fontFamily": "Times New Roman",
        "fontSize": "16px",
        "lineHeight": "2.0",
        "textIndent": "0",
    },
    "ieee": {
        "fontFamily": "Times New Roman",
        "fontSize": "13px",
        "lineHeight": "1.4",
    },
}

_SCOPES = ("paragraph", "document")
_PREVIEW_LIMIT = 40
_PREVIEW_CHARS = 20
_VERSION_KEEP = 50
_VERSION_NOTE = "AI 改版式"
_MAX_STYLE_VALUE = 60
_ANCHOR_NOTE_CHARS = 20
_MISSING = "找不到这篇草稿（可能已删除，或不是你自己的草稿）"
_NO_DRAFT = "没有指定草稿（或从页面带 scope.draft_id）"

_SAFE_VALUE_RE = re.compile(r"[\"'<>;{}\x00-\x1f\x7f]")
_WS_RE = re.compile(r"\s+")
_STYLE_ATTR_RE = re.compile(
    r"""\sstyle\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE | re.DOTALL
)
_TAG_RE = re.compile(r"<[^>]*>")


def _payload(args: dict | None) -> dict:
    """`args` 容错：None / 非 dict（模型传了奇怪形状）都当空参数。"""
    return args if isinstance(args, dict) else {}


def _draft_id_of(payload: dict, scope: Any) -> int | None:
    """先看参数、再看页面带来的 `scope`；取不到返回 None（不抛异常）。"""
    candidates = [payload.get("draft_id")]
    if isinstance(scope, dict):
        candidates.append(scope.get("draft_id"))
    for raw in candidates:
        if raw is None or raw == "" or isinstance(raw, bool):
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return None


def _normalize_ws(text: str) -> str:
    """只归并空白（换行/缩进），不改字——锚点比对仍按字面。"""
    return _WS_RE.sub(" ", text).strip()


def _clean(value: str) -> str:
    """去掉会撑破 HTML 属性的字符（值只当 CSS 用，不当代码）。"""
    return _SAFE_VALUE_RE.sub("", value).strip()


def _css_value(name: str, value: Any) -> str | None:
    """把模型给的值转成 CSS 值；转不了返回 None（调用方记成"忽略"）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if name in _PX_KEYS:
            return _clean(f"{value}px")
        return _clean(str(value)) if name == "lineHeight" else None
    if not isinstance(value, str):
        return None
    text = _clean(value)
    if not text or len(text) > _MAX_STYLE_VALUE:
        return None
    if name == "textAlign" and text not in _ALIGN_VALUES:
        return None
    return text


def _parse_style_attr(value: str | None) -> dict[str, str]:
    """`"color: red; font-size: 12px"` → 有序 dict（同名后者覆盖）。"""
    out: dict[str, str] = {}
    for part in (value or "").split(";"):
        name, sep, val = part.partition(":")
        if not sep:
            continue
        name = name.strip().lower()
        val = val.strip()
        if name and val:
            out[name] = val
    return out


def _serialize_style(style: dict[str, str]) -> str:
    return "; ".join(f"{name}: {value}" for name, value in style.items())


def _merge_css(
    existing: dict[str, str], changes: dict[str, Any]
) -> tuple[dict[str, str], list[str]]:
    """已有声明保留、同名覆盖；返回合并结果与"不认识的键"。"""
    merged = dict(existing)
    ignored: list[str] = []
    for key, raw_value in changes.items():
        name = str(key).strip()
        if name == "bold":
            if raw_value is True:
                continue
            ignored.append(name)
            continue
        css_name = _CSS_MAP.get(name)
        css_value = _css_value(name, raw_value)
        if css_name is None or css_value is None:
            ignored.append(name)
            continue
        merged[css_name] = css_value
    return merged, ignored


@dataclass
class _Block:
    """一个块元素的源码区间（只替换它，别处一个字节都不动）。"""

    tag: str
    start: int
    open_end: int
    close_start: int
    end: int
    style: dict[str, str] = field(default_factory=dict)
    inherited: dict[str, str] = field(default_factory=dict)
    text: str = ""
    index: int = -1


@dataclass
class _Element:
    tag: str
    style: dict[str, str]
    block: _Block | None = None


def _attr(attrs: list[tuple[str, str | None]], name: str) -> str | None:
    for key, value in attrs:
        if key == name:
            return value
    return None


class _Scanner(HTMLParser):
    """扫出所有块元素的源码区间，顺带记住祖先的 style（算"实际字号"）。"""

    def __init__(self, raw: str) -> None:
        super().__init__(convert_charrefs=False)
        self.raw = raw
        self._line_starts = [0]
        for line in raw.splitlines(keepends=True):
            self._line_starts.append(self._line_starts[-1] + len(line))
        self._stack: list[_Element] = []
        self.blocks: list[_Block] = []

    def _pos(self) -> int:
        line, offset = self.getpos()
        index = line - 1
        if 0 <= index < len(self._line_starts):
            return self._line_starts[index] + offset
        return len(self.raw)

    def _tag_end(self, pos: int) -> int:
        close = self.raw.find(">", pos)
        return len(self.raw) if close < 0 else close + 1

    def _inherited(self) -> dict[str, str]:
        merged: dict[str, str] = {}
        for element in self._stack:
            merged.update(element.style)
        return merged

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag in _VOID_TAGS:
            return
        pos = self._pos()
        style = _parse_style_attr(_attr(attrs, "style"))
        open_end = self._tag_end(pos)
        block = None
        if tag in _BLOCK_TAGS:
            block = _Block(
                tag=tag,
                start=pos,
                open_end=open_end,
                close_start=len(self.raw),
                end=len(self.raw),
                style=style,
                inherited=self._inherited(),
            )
            self.blocks.append(block)
        self._stack.append(_Element(tag=tag, style=style, block=block))

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag not in _BLOCK_TAGS:
            return
        pos = self._pos()
        open_end = self._tag_end(pos)
        self.blocks.append(
            _Block(
                tag=tag,
                start=pos,
                open_end=open_end,
                close_start=open_end,
                end=open_end,
                style=_parse_style_attr(_attr(attrs, "style")),
                inherited=self._inherited(),
            )
        )

    def handle_endtag(self, tag: str) -> None:
        pos = self._pos()
        while self._stack:
            element = self._stack.pop()
            if element.block is not None:
                element.block.close_start = pos
                element.block.end = self._tag_end(pos)
            if element.tag == tag:
                break


def _plain_text(fragment: str) -> str:
    """块内纯文本：去标签、还原实体（锚点就在它里面找）。"""
    return unescape(_TAG_RE.sub("", fragment))


def _leaf_blocks(raw: str) -> list[_Block]:
    """取**最内层**的块：`li` 里的 `p` 算一段，`li` 本身不算。"""
    scanner = _Scanner(raw)
    try:
        scanner.feed(raw)
        scanner.close()
    except Exception:  # noqa: BLE001 - 坏 HTML 不许把整次调用打死
        return []
    blocks = scanner.blocks
    leaves: list[_Block] = []
    for block in blocks:
        nested = any(
            other is not block
            and other.start > block.start
            and other.end <= block.end
            and other.end > other.start
            for other in blocks
        )
        if not nested:
            leaves.append(block)
    for index, block in enumerate(leaves):
        block.index = index
        block.text = _plain_text(raw[block.open_end : block.close_start])
    return leaves


def _find_blocks(blocks: list[_Block], anchor: str) -> list[_Block]:
    """逐字找锚点；只在空白（换行/缩进）上归一，不做任何模糊匹配。"""
    hits = [block for block in blocks if anchor in block.text]
    if hits:
        return hits
    normalized = _normalize_ws(anchor)
    if not normalized:
        return []
    return [
        block for block in blocks if normalized in _normalize_ws(block.text)
    ]


def _wrap_bold(content: str) -> str:
    """`<strong>` 包住块内文本；里面的 `<span style>` 等结构原样保留。"""
    core = content.strip()
    if not core:
        return content
    if core.startswith("<strong>") and core.endswith("</strong>"):
        return content
    head = content[: len(content) - len(content.lstrip())]
    tail = content[len(content.rstrip()) :]
    return f"{head}<strong>{core}</strong>{tail}"


def _set_style_attr(open_tag: str, style: dict[str, str]) -> str:
    """把合并后的样式写回开标签（没有 style 属性就补一个）。"""
    serialized = _serialize_style(style)
    match = _STYLE_ATTR_RE.search(open_tag)
    if match is not None:
        head = open_tag[: match.start()]
        tail = open_tag[match.end() :]
        return f'{head} style="{serialized}"{tail}'
    if not serialized:
        return open_tag
    close = open_tag.rfind("/>")
    if close < 0:
        close = open_tag.rfind(">")
    if close < 0:
        return open_tag
    return f'{open_tag[:close]} style="{serialized}"{open_tag[close:]}'


def _apply_changes(
    raw: str, blocks: list[_Block], changes: dict[str, Any]
) -> tuple[str, list[int], list[str]]:
    """只重写目标块的开标签与内容；返回新 HTML、改动的块序号、忽略的键。"""
    edits: list[tuple[int, int, int, int, str, str]] = []
    ignored: list[str] = []
    for block in blocks:
        merged, skipped = _merge_css(block.style, changes)
        if skipped and not ignored:
            ignored = skipped
        open_tag = raw[block.start : block.open_end]
        new_open = _set_style_attr(open_tag, merged)
        content = raw[block.open_end : block.close_start]
        new_content = (
            _wrap_bold(content) if changes.get("bold") is True else content
        )
        if new_open == open_tag and new_content == content:
            continue
        edits.append(
            (
                block.start,
                block.open_end,
                block.close_start,
                block.index,
                new_open,
                new_content,
            )
        )
    changed: list[int] = []
    for start, open_end, close_start, index, new_open, new_content in sorted(
        edits, key=lambda item: item[0], reverse=True
    ):
        raw = f"{raw[:start]}{new_open}{new_content}{raw[close_start:]}"
        changed.append(index)
    return raw, sorted(changed), ignored


def _preview_item(block: _Block) -> dict:
    """一块的现状：前 20 字、自己身上的 style、实际生效的字号与字体。"""
    effective = dict(block.inherited)
    effective.update(block.style)
    return {
        "index": block.index,
        "text": block.text.strip()[:_PREVIEW_CHARS],
        "style": _serialize_style(block.style),
        "fontFamily": effective.get("font-family"),
        "fontSize": effective.get("font-size"),
        "lineHeight": effective.get("line-height"),
    }


def _preview(blocks: list[_Block]) -> list[dict]:
    return [_preview_item(block) for block in blocks[:_PREVIEW_LIMIT]]


def _describe(changes: dict[str, Any]) -> str:
    """把样式字典说成人话（`note` 用）。"""
    parts: list[str] = []
    font = _css_value("fontFamily", changes.get("fontFamily"))
    if font:
        parts.append(font)
    size = _css_value("fontSize", changes.get("fontSize"))
    if size:
        parts.append(size)
    line = _css_value("lineHeight", changes.get("lineHeight"))
    if line:
        parts.append(f"行距 {line}")
    indent = _css_value("textIndent", changes.get("textIndent"))
    if indent:
        parts.append("不缩进" if indent == "0" else f"首行缩进 {indent}")
    align = changes.get("textAlign")
    if isinstance(align, str) and align in _ALIGN_LABELS:
        parts.append(_ALIGN_LABELS[align])
    spacing = _css_value("paragraphSpacing", changes.get("paragraphSpacing"))
    if spacing:
        parts.append(f"段后 {spacing}")
    if changes.get("bold") is True:
        parts.append("加粗")
    return "、".join(parts) or "（没有可用的样式键）"


def _build_note(
    scope: str,
    anchor: str,
    template: str,
    changes: dict[str, Any],
    changed: int,
    hit_count: int,
) -> str:
    """一句人话：改了哪些、改成什么。"""
    desc = _describe(changes)
    if scope == "paragraph":
        shown = anchor
        if len(shown) > _ANCHOR_NOTE_CHARS:
            shown = f"{shown[:_ANCHOR_NOTE_CHARS]}…"
        where = f"含「{shown}」那一段"
    else:
        where = f"整篇 {changed} 段"
    verb = f"已按 {template} 体例把" if template else "已把"
    note = f"{verb}{where}设为{desc}"
    if scope == "paragraph" and hit_count > 1:
        note += f"（另外 {hit_count - 1} 段也有这段文字，只改了第一段）"
    return note


def _load_draft(session, user_id: int, draft_id: int) -> Draft | None:
    """按 `ctx.user_id` 取归属；不存在或不是本人的一律 None。"""
    return session.scalar(
        select(Draft).where(Draft.id == draft_id, Draft.user_id == user_id)
    )


def _record_version(session, draft: Draft) -> DraftVersion:
    """写入**改前**的整篇快照（必须在 `body_html` 被改之前调用）。"""
    row = DraftVersion(
        draft_id=draft.id,
        body_md=draft.body_md or "",
        body_html=draft.body_html,
        title=draft.title or "",
        source="ai",
        note=_VERSION_NOTE,
    )
    session.add(row)
    session.flush()
    _prune_versions(session, draft.id)
    return row


def _prune_versions(session, draft_id: int) -> None:
    """只留最近 `_VERSION_KEEP` 版（与 `routers/drafts.py` 同一口径）。"""
    stale = session.scalars(
        select(DraftVersion.id)
        .where(DraftVersion.draft_id == draft_id)
        .order_by(DraftVersion.id.desc())
        .offset(_VERSION_KEEP)
    ).all()
    if stale:
        session.execute(
            delete(DraftVersion).where(DraftVersion.id.in_(list(stale)))
        )


def preview_styles(ctx: ToolContext, args: dict | None = None) -> ToolResult:
    """只读：每段的前 20 字 + 当前 style + 实际字号/字体（最多 40 段）。"""
    payload = _payload(args)
    draft_id = _draft_id_of(payload, getattr(ctx, "scope", None))
    if draft_id is None:
        return ToolResult(data=[], note=_NO_DRAFT)

    with SessionLocal() as session:
        draft = _load_draft(session, ctx.user_id, draft_id)
        if draft is None:
            return ToolResult(data=[], note=_MISSING)
        body_html = draft.body_html or ""

    if not body_html.strip():
        return ToolResult(
            data=[], note="这篇还没有富文本正文（body_html 为空），没有版式可看"
        )
    blocks = _leaf_blocks(body_html)
    if not blocks:
        return ToolResult(
            data=[],
            note="body_html 里没有可识别的块（p / h1–h3 / li / blockquote）",
        )
    items = _preview(blocks)
    note = f"{len(items)} 段"
    if len(blocks) > _PREVIEW_LIMIT:
        note = f"共 {len(blocks)} 段，只显示前 {_PREVIEW_LIMIT} 段"
    note += "；改版式用 apply_style"
    return ToolResult(data=items, note=note)


def apply_style(ctx: ToolContext, args: dict | None = None) -> ToolResult:
    """改版式：单段 / 整篇 / 按体例；`dry_run=true` 只看不改。"""
    payload = _payload(args)
    draft_id = _draft_id_of(payload, getattr(ctx, "scope", None))
    if draft_id is None:
        return ToolResult(data={"error": _NO_DRAFT}, note=_NO_DRAFT)

    scope = str(payload.get("scope") or "").strip().lower()
    anchor = str(payload.get("anchor") or "").strip()
    template = str(payload.get("template") or "").strip().lower()
    dry_run = payload.get("dry_run") is True
    raw_style = payload.get("style")
    style = dict(raw_style) if isinstance(raw_style, dict) else {}

    if scope not in _SCOPES:
        valid = " / ".join(_SCOPES)
        given = scope or "空"
        return ToolResult(
            data={"error": "scope 不对"},
            note=f"scope 只能是 {valid}，你给的是「{given}」",
        )
    if scope == "paragraph" and not anchor:
        return ToolResult(
            data={"error": "缺少 anchor"},
            note="scope=paragraph 必须给 anchor：那一段里连续出现的一小段原文",
        )
    if template and template not in _TEMPLATES:
        available = " / ".join(_TEMPLATES)
        return ToolResult(
            data={"error": "体例不存在"},
            note=f"没有这个体例「{template}」，可用：{available}",
        )

    changes: dict[str, Any] = dict(_TEMPLATES[template]) if template else {}
    changes.update(style)
    if not changes:
        return ToolResult(
            data={"error": "没有样式"},
            note="没给 style 也没给 template，不知道要改成什么样",
        )

    with SessionLocal() as session:
        draft = _load_draft(session, ctx.user_id, draft_id)
        if draft is None:
            return ToolResult(data={"error": _MISSING}, note=_MISSING)
        before_html = draft.body_html or ""
        if not before_html.strip():
            note = "这篇还没有富文本正文（body_html 为空），没有可改的版式"
            return ToolResult(data={"error": note}, note=note)

        blocks = _leaf_blocks(before_html)
        if not blocks:
            note = "body_html 里没有可识别的块（p / h1–h3 / li / blockquote）"
            return ToolResult(data={"error": note}, note=note)

        targets = blocks
        hit_count = len(blocks)
        if scope == "paragraph":
            targets = _find_blocks(blocks, anchor)
            if not targets:
                return ToolResult(
                    data={"error": "anchor 对不上"},
                    note="稿子里没有这段文字，别硬改",
                )
            hit_count = len(targets)
            targets = targets[:1]

        new_html, changed, ignored = _apply_changes(
            before_html, targets, changes
        )
        if new_html == before_html:
            return ToolResult(
                data={
                    "draft_id": draft.id,
                    "scope": scope,
                    "changed": 0,
                    "changed_blocks": [],
                    "preview": _preview(blocks),
                    "version": None,
                    "dry_run": dry_run,
                },
                note="这几段的样式已经是这样了，没有改动",
            )

        note = _build_note(scope, anchor, template, changes, len(changed), hit_count)
        if ignored:
            note += f"；不认识的样式键已忽略：{'、'.join(ignored)}"

        data = {
            "draft_id": draft.id,
            "scope": scope,
            "changed": len(changed),
            "changed_blocks": changed,
            "preview": _preview(_leaf_blocks(new_html)),
            "version": None,
            "dry_run": dry_run,
        }
        if dry_run:
            return ToolResult(data=data, note=f"预览（没有写库）：{note}")

        version = _record_version(session, draft)
        draft.body_html = new_html
        session.commit()
        data["version"] = version.id
        return ToolResult(data=data, note=note)


PACK = Pack(
    name="format",
    tools=(
        ToolSpec(
            name="preview_styles",
            description=(
                "看草稿每段现在的版式：前 20 字 + 当前 style + 实际字号/字体"
                "（最多 40 段）。改版式之前先调它，别凭想象改。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "draft_id": {
                        "type": "integer",
                        "description": "草稿 id，省略就用当前草稿",
                    },
                },
                "additionalProperties": False,
            },
            handler=preview_styles,
            max_result_chars=4000,
        ),
        ToolSpec(
            name="apply_style",
            description=(
                "改草稿版式（字体/字号/行距/缩进/对齐/加粗/段距）："
                "scope=paragraph 改 anchor 那一段，scope=document 改整篇；"
                "template 给体例默认值（cn-journal / apa / ieee），style 覆盖它。"
                "每次真改会先存一版以便撤销；dry_run=true 只看不改。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "draft_id": {
                        "type": "integer",
                        "description": "草稿 id，省略就用当前草稿",
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["paragraph", "document"],
                        "description": "paragraph=只改 anchor 那一段；document=整篇",
                    },
                    "anchor": {
                        "type": "string",
                        "description": (
                            "scope=paragraph 时必填：那一段里连续的一小段原文"
                            "（逐字，不许改写）"
                        ),
                    },
                    "style": {
                        "type": "object",
                        "description": (
                            "fontFamily(宋体) / fontSize(16px) / lineHeight(1.8) / "
                            "textIndent(2em) / textAlign(left|center|right) / "
                            "bold(true) / paragraphSpacing(10px)"
                        ),
                    },
                    "template": {
                        "type": "string",
                        "enum": ["cn-journal", "apa", "ieee"],
                        "description": "体例默认值；style 里的键会覆盖它",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "true 只返回会改哪几块、改成什么，不写库",
                    },
                },
                "required": ["scope"],
                "additionalProperties": False,
            },
            handler=apply_style,
            max_result_chars=6000,
        ),
    ),
)
