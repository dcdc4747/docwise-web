"""把写作页的 HTML 正文解析成 docx 可用的结构化片段（纯函数）。

只依赖标准库 `html.parser`，**不 import python-docx**，不碰数据库。

签名：

- `parse_body_html(body_html) -> list[dict]`：
  输入 `body_html: str`，输出 `list[dict]`，每项键固定为
  `text` / `level` / `bold` / `font_family` / `font_size_pt` /
  `line_height` / `first_line_indent_pt` / `align`。
- `parse_body_html_checked(body_html) -> (list[dict], str | None)`：
  同上，另给一个**回退信号**：第二项为 `None` 表示解析成功；
  非 `None` 是失败原因（中文短语），调用方据此走旧路径。

规则（写死，别自己发明）：

1. `<h1>`..`<h3>` → `level` 1..3；`<p>` / `<blockquote>` → 0；
   `<li>` → 0，且 `text` 前缀 `• `（中点 + 空格）。
2. 继承只认块**自己**的 `style`：本任务的 HTML 是扁平的，
   不往祖先找字号；祖先只用来识别 `li` / `blockquote` 容器。
3. `px → pt`：`pt = px * 0.75`；`text-indent` 的 `em`
   按**该块字号**折算（`2em` × 12pt = 24pt）。
4. `font-family` 取第一个字族并去引号
   （`"Kaiti SC", KaiTi, serif` → `Kaiti SC`）。
5. `<span style="font-size:22px">` 的段内字号**覆盖整块**字号
   （不做 run 切分，够用即可）。
6. 没有 `style` 的块：装饰字段为 `None`、`bold` 为 `False`。
7. **绝不抛异常**：脏 HTML 返回 `[]`；失败原因由
   `parse_body_html_checked` 给出，调用方回退旧路径。

其他口径：

- `line_height` 统一折算成**倍数**（Word 的行距倍数）：
  无单位 `1.5` / `150%` → 1.5；`24px` 且字号 16px → 1.5。
- `first_line_indent_pt` 允许负数（悬挂缩进按原值透传）。
- `align` 只透传 `left/center/right/justify`；`start/end`
  折成 `left/right`，其余值给 `None`（不猜）。
- `bold` 认三样：`font-weight` ≥ 600、`bold` / `bolder`、
  块内出现 `<strong>` / `<b>`（粗粒度：整块算粗）。
- 字号只认 `px` / `pt`；`em` / `rem` / `%` 字号返回 `None`
  （祖先字号不参与继承，硬折算等于编）。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

# CSS 96dpi 口径：1px = 0.75pt。
_PX_TO_PT = 0.75

# `em` 折算的兜底字号：CSS 默认 16px = 12pt（块没写字号时用）。
_DEFAULT_FONT_PT = 12.0

_HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3}
_BLOCK_TAGS = frozenset({"h1", "h2", "h3", "p", "li", "blockquote"})
_BOLD_TAGS = frozenset({"strong", "b"})
_INLINE_TAGS = frozenset(
    {"span", "strong", "b", "em", "i", "u", "s", "code", "sub", "sup", "mark", "a"}
)
# 这两个标签里的内容不是正文；整段跳过。
_SKIP_TAGS = frozenset({"script", "style"})

_NUMBER_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*(px|pt|em|rem|%)?\s*$", re.IGNORECASE)
_SPACES_RE = re.compile(r"[ \t\f\v]+")
_ALIGN_VALUES = {"left", "center", "right", "justify"}
_ALIGN_ALIASES = {"start": "left", "end": "right"}

REASON_EMPTY = "没有 HTML 正文"
REASON_FAILED = "HTML 解析失败"
REASON_NO_BLOCKS = "HTML 里没有可导出的块"


# ============================================================ 小工具

def _parse_style(value: str | None) -> dict[str, str]:
    """`"font-size: 16px; color: red"` → 有序 dict（同名后者覆盖）。"""
    style: dict[str, str] = {}
    for part in (value or "").split(";"):
        name, sep, raw = part.partition(":")
        if not sep:
            continue
        name = name.strip().lower()
        raw = raw.strip()
        if name and raw:
            style[name] = raw
    return style


def _number(value: str | None) -> tuple[float, str] | None:
    """拆 `"16px"` / `"1.5"` → `(16.0, "px")`；不认识的写法则 None。"""
    match = _NUMBER_RE.match(value or "")
    if not match:
        return None
    unit = (match.group(2) or "").lower()
    try:
        return float(match.group(1)), unit
    except ValueError:
        return None


def _rounded(value: float) -> float:
    return round(value, 4)


def _font_size_pt(value: str | None) -> float | None:
    """字号：`px` / `pt` 认，其余单位（em/rem/%）不猜。"""
    parsed = _number(value)
    if parsed is None:
        return None
    size, unit = parsed
    if unit == "px":
        return _rounded(size * _PX_TO_PT)
    if unit == "pt":
        return _rounded(size)
    return None


def _font_family(value: str | None) -> str | None:
    """取第一个字族并去引号；空值/空串一律 None。"""
    raw = (value or "").split(",")[0].strip()
    raw = raw.strip("\"'").strip()
    return raw or None


def _style_is_bold(style: dict[str, str]) -> bool:
    weight = style.get("font-weight", "").strip().lower()
    if weight in {"bold", "bolder"}:
        return True
    try:
        return float(weight) >= 600
    except ValueError:
        return False


def _text_indent_pt(value: str | None, size_pt: float | None) -> float | None:
    """首行缩进：`px` / `pt` 直接换算，`em` 按该块字号折算。"""
    parsed = _number(value)
    if parsed is None:
        return None
    amount, unit = parsed
    if unit == "px":
        return _rounded(amount * _PX_TO_PT)
    if unit == "pt":
        return _rounded(amount)
    if unit in {"em", "rem"}:
        base = size_pt if size_pt is not None else _DEFAULT_FONT_PT
        return _rounded(amount * base)
    if unit == "" and amount == 0:
        return 0.0
    return None


def _line_height(value: str | None, size_pt: float | None) -> float | None:
    """行距统一成倍数：无单位/百分比是倍数，绝对长度按字号折算。"""
    parsed = _number(value)
    if parsed is None:
        return None
    amount, unit = parsed
    if amount <= 0:
        return None
    if unit == "":
        return _rounded(amount)
    if unit == "%":
        return _rounded(amount / 100)
    if unit in {"em", "rem"}:
        return _rounded(amount)
    base = size_pt if size_pt is not None else _DEFAULT_FONT_PT
    if unit == "px":
        return _rounded(amount * _PX_TO_PT / base)
    if unit == "pt":
        return _rounded(amount / base)
    return None


def _align(value: str | None) -> str | None:
    """只透传四个合法值；`start/end` 折成 `left/right`，其余 None。"""
    text = (value or "").strip().lower()
    text = _ALIGN_ALIASES.get(text, text)
    return text if text in _ALIGN_VALUES else None


def _clean_text(raw: str) -> str:
    """收拢空白（不丢 `<br>` 带来的换行），空行去掉。"""
    text = raw.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines = [_SPACES_RE.sub(" ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def _style_of(attrs: list[tuple[str, str | None]]) -> str | None:
    for name, value in attrs:
        if name.lower() == "style":
            return value
    return None


# ============================================================ 解析器

class _HtmlBlockParser(HTMLParser):
    """按文档顺序扫出块；`li` / `blockquote` 里的 `p` 不再另起一段。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict[str, Any]] = []
        self._stack: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None
        self._containers = 0
        self._skip = 0

    # -- 供 `parse_body_html_checked` 收尾
    def finish(self) -> None:
        self._finish()

    # -- 文本
    def handle_data(self, data: str) -> None:
        if self._skip or not data:
            return
        self._append(data)

    def _append(self, text: str) -> None:
        block = self._current
        if block is None:
            if not text.strip():
                return
            self._finish()
            block = self._new_block("p", {})
            self._current = block
        block["parts"].append(text)
        if block["inline_size"] is None:
            size = self._nearest_inline_size()
            if size is not None:
                block["inline_size"] = size

    def _nearest_inline_size(self) -> float | None:
        for record in reversed(self._stack):
            if record["inline"] is not None:
                return record["inline"]
        return None

    # -- 标签
    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if self._skip:
            return
        style = _parse_style(_style_of(attrs))
        if tag == "br":
            self._append("\n")
            return
        if tag in _BLOCK_TAGS:
            self._enter_block(tag, style)
            return
        inline: float | None = None
        if tag in _INLINE_TAGS:
            inline = _font_size_pt(style.get("font-size"))
            if tag in _BOLD_TAGS and self._current is not None:
                self._current["bold"] = True
        self._stack.append(
            {"tag": tag, "block": None, "container": False, "inline": inline}
        )

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            if self._skip:
                self._skip -= 1
            return
        if self._skip:
            return
        index: int | None = None
        for position in range(len(self._stack) - 1, -1, -1):
            if self._stack[position]["tag"] == tag:
                index = position
                break
        if index is None:
            return
        while len(self._stack) > index:
            record = self._stack.pop()
            if record["container"]:
                self._containers = max(0, self._containers - 1)
            if record["block"] is self._current and record["block"] is not None:
                self._finish()

    def _enter_block(self, tag: str, style: dict[str, str]) -> None:
        if tag in {"p", "blockquote"} and self._containers:
            # 列表项 / 引文里的 p 不另起段：文字归外层块，别切成两段。
            self._stack.append(
                {"tag": tag, "block": None, "container": False, "inline": None}
            )
            return
        self._finish()
        block = self._new_block(tag, style)
        self._current = block
        container = tag in {"li", "blockquote"}
        if container:
            self._containers += 1
        self._stack.append(
            {"tag": tag, "block": block, "container": container, "inline": None}
        )

    @staticmethod
    def _new_block(tag: str, style: dict[str, str]) -> dict[str, Any]:
        return {
            "tag": tag,
            "style": style,
            "level": _HEADING_LEVELS.get(tag, 0),
            "bold": _style_is_bold(style),
            "parts": [],
            "inline_size": None,
            "prefix": "• " if tag == "li" else "",
        }

    def _finish(self) -> None:
        block = self._current
        if block is None:
            return
        self._current = None
        style = block["style"]
        text = _clean_text("".join(block["parts"]))
        if not text:
            return
        if block["prefix"]:
            text = block["prefix"] + text
        size = block["inline_size"]
        if size is None:
            size = _font_size_pt(style.get("font-size"))
        self.blocks.append(
            {
                "text": text,
                "level": block["level"],
                "bold": bool(block["bold"]),
                "font_family": _font_family(style.get("font-family")),
                "font_size_pt": size,
                "line_height": _line_height(style.get("line-height"), size),
                "first_line_indent_pt": _text_indent_pt(
                    style.get("text-indent"), size
                ),
                "align": _align(style.get("text-align")),
            }
        )


# ============================================================ 对外入口

def parse_body_html(body_html: str | None) -> list[dict[str, Any]]:
    """解析 HTML；**任何输入都不抛异常**，解析不出就返回 `[]`。"""
    blocks, _reason = parse_body_html_checked(body_html)
    return blocks


def parse_body_html_checked(
    body_html: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    """解析 HTML，并给出回退信号：`(blocks, reason)`。

    `reason is None` → 解析成功；否则调用方应回退 Markdown 旧路径。
    """
    if not isinstance(body_html, str) or not body_html.strip():
        return [], REASON_EMPTY
    parser = _HtmlBlockParser()
    try:
        parser.feed(body_html)
        parser.close()
        parser.finish()
    except Exception:
        # 脏 HTML / 解析器自身缺陷都不许把导出打死。
        return [], REASON_FAILED
    if not parser.blocks:
        return [], REASON_NO_BLOCKS
    return parser.blocks, None
