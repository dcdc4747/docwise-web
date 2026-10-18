"""综述矩阵工具包：把同主题的若干篇文献排成一张"综述矩阵"。

用途：老师写综述时最费时的一步是"把十几篇的研究问题 / 方法 / 结论抄成一张表"。
这里把**已经生成过的**导读与术语表按文献排成行，再附一句该篇被引用过的原文，
模型据此汇总，而不是自己编。

口径（与 `compare.py` 同一套）：

- 只读：不写库、不调模型、不 import pydantic_ai；
- 归属：只看 `ctx.user_id` 的文献，别人的一律看不见（软删的也不列）；
- `research_question` / `method` / `conclusion` 只从导读取，
  取不到写 `None`，**不编**；
- 没有导读的文献进 `missing`，**不塞进 rows 假装有内容**；
- `quote` 只取该篇**被引文引用过的素材**里第一条 `text_quote`，没有就 `null`。

`guide_json` 的两种形状都认：`{字段: {"text": …, "source_block_ids": […]}}`
（现在写的）与 `{字段: "文本"}`（早期/手写）。`terms_json` 认数组
`[{term, cn, definition}]`，也兼容 `{"terms": […]}`。
"""

from __future__ import annotations

import json

from sqlalchemy import select

from ...db import SessionLocal
from ...models import Citation, Draft, Material, Task, TaskUnderstanding
from ..contracts import Pack, ToolResult, ToolSpec

# 矩阵的固定列（顺序即界面/模型看到的顺序）
_COLUMNS = ("文献", "研究问题", "方法", "结论", "术语", "可引用句")
# 只取导读的三个键；其它键（创新点/贡献…）不塞进矩阵
_GUIDE_FIELDS = ("research_question", "method", "conclusion")
_TERMS_LIMIT = 5
_DEFAULT_LIMIT = 10
_MAX_LIMIT = 30
# 一次最多看多少篇再筛（防止把整库都读进内存；超出部分不参与主题匹配）
_SCAN_LIMIT = 200
# 引用原文的预览长度：矩阵是"表格"，长段落截断并标明，不改变出处
_QUOTE_CHARS = 300


def _payload(args: dict | None) -> dict:
    """`args` 容错：None / 非 dict 都当空参数。"""
    return args if isinstance(args, dict) else {}


def _as_int(value) -> int | None:
    """宽松转 int；转不了返回 None（不抛异常）。"""
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _json_obj(raw):
    """理解层存的是 JSON 字符串；读坏了返回 None，绝不抛异常。"""
    if isinstance(raw, (dict, list)):
        return raw
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _guide_text(value) -> str:
    """导读字段的真实结构是 `{"text": …, "source_block_ids": […]}`。"""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str):
            return text.strip()
    return ""


def _guide_texts(raw) -> dict[str, str]:
    """只收有非空文本的字段；空字段等同于「没有」。"""
    data = _json_obj(raw)
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in data.items():
        text = _guide_text(value)
        if text:
            out[str(key)] = text
    return out


def _terms(raw) -> list[str]:
    """术语表取前 5 个 `term`；数组与 `{"terms": […]}` 两种形状都认。"""
    data = _json_obj(raw)
    if isinstance(data, dict):
        data = data.get("terms") or []
    if not isinstance(data, list):
        return []
    out: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        term = str(
            item.get("term") or item.get("source") or item.get("en") or ""
        ).strip()
        if term:
            out.append(term)
        if len(out) >= _TERMS_LIMIT:
            break
    return out


def _quote_preview(text: str) -> str:
    """长引用截断并标明（矩阵是表格，不是全文）；不改写内容。"""
    cleaned = text.strip()
    if len(cleaned) <= _QUOTE_CHARS:
        return cleaned
    return cleaned[:_QUOTE_CHARS].rstrip() + "…"


def _first_cited_quote(db, task_id: int, user_id: int) -> str | None:
    """该篇**被引文引用过**的素材里第一条非空 `text_quote`；没有就 None。

    只认当前用户自己的草稿与素材（别人的引用不算）。
    """
    rows = db.execute(
        select(Material.text_quote)
        .join(Citation, Citation.material_id == Material.id)
        .join(Draft, Draft.id == Citation.draft_id)
        .where(
            Material.task_id == task_id,
            Material.user_id == user_id,
            Draft.user_id == user_id,
        )
        .order_by(Citation.order, Citation.id)
    ).all()
    for (text,) in rows:
        if text and text.strip():
            return _quote_preview(text)
    return None


def _matches(topic: str, filename: str, guide_texts: dict[str, str]) -> bool:
    """主题匹配：文件名或导读文本里包含主题词（大小写不敏感）。"""
    if not topic:
        return True
    needle = topic.casefold()
    if needle in (filename or "").casefold():
        return True
    return needle in " ".join(guide_texts.values()).casefold()


def _empty(topic: str, note: str) -> ToolResult:
    return ToolResult(
        data={
            "topic": topic,
            "columns": list(_COLUMNS),
            "rows": [],
            "missing": [],
        },
        note=note,
    )


def build_matrix(ctx, args: dict | None = None) -> ToolResult:
    """把同主题文献排成矩阵；缺导读的进 `missing`，读不到就直说。"""
    payload = _payload(args)
    raw_topic = payload.get("topic")
    topic = raw_topic.strip() if isinstance(raw_topic, str) else ""
    limit = _as_int(payload.get("limit"))
    if limit is None:
        limit = _DEFAULT_LIMIT
    limit = max(1, min(limit, _MAX_LIMIT))

    with SessionLocal() as db:
        rows = db.execute(
            select(Task, TaskUnderstanding)
            .outerjoin(
                TaskUnderstanding, TaskUnderstanding.task_id == Task.id
            )
            .where(Task.user_id == ctx.user_id, Task.deleted_at.is_(None))
            .order_by(Task.created_at.desc(), Task.id.desc())
            .limit(_SCAN_LIMIT)
        ).all()

        # 先按主题筛，再把"有导读的"稳定地提到前面（组内仍按最近排序）
        candidates: list[tuple[Task, TaskUnderstanding | None, dict[str, str]]] = []
        for task, understanding in rows:
            texts = _guide_texts(
                understanding.guide_json if understanding else None
            )
            if not _matches(topic, task.filename or "", texts):
                continue
            candidates.append((task, understanding, texts))
        candidates.sort(key=lambda item: 0 if item[2] else 1)

        selected = candidates[:limit]
        hidden = len(candidates) - len(selected)

        data_rows: list[dict] = []
        missing: list[dict] = []
        for task, understanding, texts in selected:
            if not texts:
                missing.append({"task_id": task.id, "why": "还没有导读"})
                continue
            data_rows.append(
                {
                    "task_id": task.id,
                    "file": task.filename or "",
                    "research_question": texts.get("research_question"),
                    "method": texts.get("method"),
                    "conclusion": texts.get("conclusion"),
                    "terms": _terms(
                        understanding.terms_json if understanding else None
                    ),
                    "quote": _first_cited_quote(db, task.id, ctx.user_id),
                }
            )

    data = {
        "topic": topic,
        "columns": list(_COLUMNS),
        "rows": data_rows,
        "missing": missing,
    }

    if not candidates:
        if topic:
            return ToolResult(data=data, note="没有匹配的文献")
        return ToolResult(data=data, note="库里还没有文献")

    notes: list[str] = []
    if data_rows:
        notes.append(f"排了 {len(data_rows)} 篇")
    if missing:
        if data_rows:
            notes.append(f"{len(missing)} 篇还没有导读")
        else:
            notes.append(f"匹配的 {len(missing)} 篇都还没有导读，排不出内容")
    if hidden:
        notes.append(f"还有 {hidden} 篇匹配但没显示（limit={limit}）")
    return ToolResult(data=data, note="；".join(notes))


PACK = Pack(
    name="matrix",
    tools=(
        ToolSpec(
            name="build_matrix",
            description=(
                "把同主题的若干篇文献排成综述矩阵：每行一篇，列是"
                "研究问题 / 方法 / 结论 / 术语 / 可引用句。"
                "只读；没有导读的文献会列进 missing，不会编内容。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": (
                            "主题词：按文件名或导读文本过滤（大小写不敏感）；"
                            "留空则取最近的文献（有导读的优先）"
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": _MAX_LIMIT,
                        "description": "最多排几篇，默认 10",
                    },
                },
                "additionalProperties": False,
            },
            handler=build_matrix,
            max_result_chars=12000,
        ),
    ),
)
