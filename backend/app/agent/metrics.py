"""术语一致率：纯函数，不查库、不依赖框架。

它只回答一件事：正文里的术语写法，跟术语表是不是一套。
调用方给正文与 `terms` 列表即可（来源可以是 `terms_json`，
也可以手写），不需要数据库、FastAPI 或模型客户端。

## 统计口径

1. 术语表里每个 dict 算一个**词条**：规范写法取 `zh`；
   `zh` 缺省时退回 `term`，再缺就跳过该条。
   `aliases` 是同一概念的其它写法。
2. `hits` = 规范写法在正文里出现的次数；
   `alias_hits` = 别名（不含规范写法本身）出现次数之和。
   英文按词边界、不区分大小写；中文按子串；重叠不算两次。
3. 每条术语一个状态：
   - `ok`：只出现规范写法；
   - `alias`：出现别名（规范写法没有在同段同现）；
   - `missing`：正文里一次都没出现。**不算错**——这篇可能
     根本没谈到它；
   - `conflict`：同一段落里规范写法与别名同时出现，
     这才是真正的不一致。
   段落按换行切分（一行一段）：宁可漏报，也不把不同段落
   的两种写法误判成冲突。
4. 一致率分母 = 正文里至少出现过一次的词条数
   （`hits + alias_hits > 0`）；分子 = 其中 `ok` 的条数。
   分母为 0 时 `rate` 返回 `None`，**不用 1.0 冒充全对**。
5. 返回的 `total` 就是分母（不是 `len(rows)`）；
   没出现的词条仍留在 `rows` 里，方便逐条查看。
   每行另带 `used_aliases`（正文里实际命中的别名），
   只给 `format_term_report` 拼人话用。
6. `examples` 最多 2 段上下文，每段含省略号在内不超过
   40 字；截断处用「…」标出，方便用户回原文定位。

引用标记（如 `[1]`）不是术语的一部分，匹配时自然不计入，
也不会把命中切开。
"""

from __future__ import annotations

import re

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_PARAGRAPH_RE = re.compile(r"\r\n|\r|\n")
_EXAMPLE_LIMIT = 40
_EXAMPLES_MAX = 2


def _spans(text: str, word: str) -> list[tuple[int, int]]:
    """返回 `word` 在 `text` 里的所有命中区间（不重叠）。"""
    if not word:
        return []
    if _CJK_RE.search(word):
        spans: list[tuple[int, int]] = []
        start = text.find(word)
        while start >= 0:
            spans.append((start, start + len(word)))
            start = text.find(word, start + len(word))
        return spans
    # 英文按词边界，大小写不敏感：chiral[1] 仍算一次命中
    pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
    return [(match.start(), match.end()) for match in pattern.finditer(text)]


def _count(text: str, word: str) -> int:
    return len(_spans(text, word))


def _paragraphs(text: str) -> list[str]:
    """按换行切段；空行不参与（它们不构成"同一段落"）。"""
    return [part for part in _PARAGRAPH_RE.split(text) if part.strip()]


def _snippet(text: str, start: int, end: int) -> str:
    """截一段带上下文的例子，含省略号不超过 40 字。"""
    if start < 0 or end > len(text) or start >= end:
        return ""
    match = text[start:end]
    head = "…" if start > 0 else ""
    tail = "…" if end < len(text) else ""
    fixed = len(match) + len(head) + len(tail)
    if fixed > _EXAMPLE_LIMIT:
        keep = _EXAMPLE_LIMIT - len(head) - len(tail) - 1
        if keep < 1:
            return match[:_EXAMPLE_LIMIT]
        core = re.sub(r"\s+", " ", match[:keep]).strip()
        return head + core + "…" + tail
    if fixed == _EXAMPLE_LIMIT:
        return head + match + tail

    room = _EXAMPLE_LIMIT - fixed
    before = min(start, room // 2)
    after = min(len(text) - end, room - before)
    before = min(start, room - after)
    core = re.sub(r"\s+", " ", text[start - before : end + after]).strip()
    if not core:
        return ""
    prefix = "…" if start - before > 0 else ""
    suffix = "…" if end + after < len(text) else ""
    return prefix + core + suffix


def _examples_of(text: str, spans: list[tuple[int, int]]) -> list[str]:
    """同一类命中的上下文例子，最多 2 段且去重。"""
    examples: list[str] = []
    for start, end in spans:
        piece = _snippet(text, start, end)
        if piece and piece not in examples:
            examples.append(piece)
        if len(examples) >= _EXAMPLES_MAX:
            break
    return examples


def _conflict_examples(
    paragraphs: list[str], zh: str, aliases: list[str]
) -> list[str]:
    """冲突例子优先取"两种写法同段"的那一段。"""
    for paragraph in paragraphs:
        zh_spans = _spans(paragraph, zh)
        alias_spans = [
            span for alias in aliases for span in _spans(paragraph, alias)
        ]
        if not zh_spans or not alias_spans:
            continue
        zh_start, zh_end = zh_spans[0]
        alias_start, alias_end = alias_spans[0]
        start = min(zh_start, alias_start)
        end = max(zh_end, alias_end)
        if end - start <= _EXAMPLE_LIMIT - 2:
            return _examples_of(paragraph, [(start, end)])
        return _examples_of(paragraph, [zh_spans[0], alias_spans[0]])
    return []


def _clean_aliases(raw: object, canonical: str) -> list[str]:
    """把输入里的 `aliases` 收拾成去重、去空、去掉规范写法本身的表。"""
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    seen = {canonical.casefold()}
    aliases: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        alias = item.strip()
        if not alias or alias.casefold() in seen:
            continue
        seen.add(alias.casefold())
        aliases.append(alias)
    return aliases


def _normalize_terms(terms: object) -> list[dict]:
    """只保留能匹配的词条；坏条目跳过，不抛异常。"""
    if not isinstance(terms, list):
        return []
    normalized: list[dict] = []
    for item in terms:
        if not isinstance(item, dict):
            continue
        term = str(item.get("term") or "").strip()
        zh = str(item.get("zh") or "").strip()
        canonical = zh or term
        if not canonical:
            continue
        normalized.append(
            {
                "term": term or canonical,
                "zh": canonical,
                "aliases": _clean_aliases(item.get("aliases"), canonical),
            }
        )
    return normalized


def term_consistency(text: str, terms: list[dict]) -> dict:
    """给定正文与术语表，算术语一致率与不一致清单。

    入参：
    - `text`：正文纯文本；`[1]` 这类引用标记不影响统计；
    - `terms`：`[{"term", "zh", "aliases"}]`，键可缺，
      `aliases` 可省略。不查库，只接收 dict。

    返回 `{"rate", "total", "ok", "rows"}`：
    - `rate`：`ok / total`；分母为 0（正文没出现任何词条，
      或术语表为空）时是 `None`；
    - `total`：分母——正文里至少出现过一次的词条数；
    - `ok`：其中只出现规范写法的条数；
    - `rows`：逐条明细，含没出现的词条（`status="missing"`）。
      每行 `{term, zh, status, hits, alias_hits, used_aliases,
      examples}`；`examples` 最多 2 段、每段不超过 40 字。

    口径细节见模块文档：同段 zh 与别名同现才算 `conflict`，
    `missing` 不计入分母（可能这篇没谈到，不算错）。
    """
    body = text if isinstance(text, str) else ""
    entries = _normalize_terms(terms)
    paragraphs = _paragraphs(body)

    rows: list[dict] = []
    total = 0
    ok_count = 0
    for entry in entries:
        zh = entry["zh"]
        aliases = entry["aliases"]
        zh_spans = _spans(body, zh)
        alias_spans = [
            span for alias in aliases for span in _spans(body, alias)
        ]
        hits = len(zh_spans)
        alias_hits = len(alias_spans)
        used_aliases = [
            alias for alias in aliases if _count(body, alias) > 0
        ]

        if hits + alias_hits == 0:
            status = "missing"
            examples: list[str] = []
        elif alias_hits == 0:
            status = "ok"
            examples = _examples_of(body, zh_spans)
        elif hits == 0:
            status = "alias"
            examples = _examples_of(body, alias_spans)
        else:
            same_paragraph = any(
                _count(paragraph, zh)
                and any(_count(paragraph, alias) for alias in aliases)
                for paragraph in paragraphs
            )
            status = "conflict" if same_paragraph else "alias"
            examples = (
                _conflict_examples(paragraphs, zh, aliases)
                if same_paragraph
                else _examples_of(body, alias_spans)
            )

        if hits + alias_hits > 0:
            total += 1
            if status == "ok":
                ok_count += 1
        rows.append(
            {
                "term": entry["term"],
                "zh": entry["zh"],
                "status": status,
                "hits": hits,
                "alias_hits": alias_hits,
                "used_aliases": used_aliases,
                "examples": examples[:_EXAMPLES_MAX],
            }
        )

    return {
        "rate": (ok_count / total) if total else None,
        "total": total,
        "ok": ok_count,
        "rows": rows,
    }


def _quoted(items: list[str]) -> str:
    return "、".join(f"「{item}」" for item in items)


def format_term_report(result: dict) -> str:
    """把上面的结果写成一句人话（给 note / 界面用）。

    形如：`术语一致率 75%（3/4）；「chiral」同时出现
    「手性」与「手征」，建议统一`。分母为 0 时如实说无法计算，
    空结果、坏字段都不会抛异常。
    """
    if not isinstance(result, dict):
        return "术语一致率无法计算"
    rows = [row for row in result.get("rows") or [] if isinstance(row, dict)]
    rate = result.get("rate")
    if not isinstance(rate, (int, float)):
        rate = None
    try:
        total = int(result.get("total") or 0)
        ok_count = int(result.get("ok") or 0)
    except (TypeError, ValueError):
        total, ok_count = 0, 0

    if rate is None or total <= 0:
        if not rows:
            return "术语一致率无法计算（术语表为空）"
        return (
            "术语一致率无法计算"
            f"（{len(rows)} 条术语都没在这段正文里出现）"
        )

    head = f"术语一致率 {rate * 100:.0f}%（{ok_count}/{total}）"
    advice: list[str] = []
    for row in rows:
        status = row.get("status")
        term = str(row.get("term") or row.get("zh") or "")
        zh = str(row.get("zh") or term)
        used = [
            str(alias)
            for alias in row.get("used_aliases") or []
            if alias
        ]
        if status == "conflict":
            other = _quoted(used) if used else "别名"
            advice.append(
                f"「{term}」同时出现「{zh}」与{other}，建议统一"
            )
        elif status == "alias" and used:
            advice.append(
                f"「{term}」用了别名{_quoted(used)}，建议统一为「{zh}」"
            )

    if not advice:
        return head + "，术语用法一致"
    return head + "；" + "；".join(advice[:3])
