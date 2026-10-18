"""只读检索服务：FTS5（trigram）召回，**按用户收口**。

为什么单独一层：`routers/ask.py` 与 agent 的工具都要检索，
以前这段写在路由里，agent 要用就只能反向 import 路由（破坏隔离）。
搬到这里之后：**routers → services ← packs**。

⚠️ 与 `ask.py` 里的老实现保持同一套口径（trigram 最少 3 字、短 CJK 用 LIKE 兜底），
否则"问答查得到、agent 查不到"会变成很难查的差异。
"""

from __future__ import annotations

import re
from sqlite3 import OperationalError

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..models import Task, TaskBlock

# CJK 常用虚词/代词：检索时滤掉，避免命中噪声
_CJK_STOPWORDS = set("的了吗呢么吧啊呀这那我你他她它在是有和与或就不都也很")
_DEFAULT_LIMIT = 8

# ⚠️ 回收站的 `deleted_at` 与这份代码可能**不同时存在**（分属两个 PR）。
# 有这一列就排除回收站；没有就先只按归档过滤——合并顺序不该影响检索结果。
_HAS_TRASH = hasattr(Task, "deleted_at")
_TRASH_SQL = "AND t.deleted_at IS NULL " if _HAS_TRASH else ""


def query_tokens(question: str) -> list[str]:
    """问题 → trigram 兼容的检索词（ASCII 词原样；CJK 去虚词后滑窗取 3 字）。"""
    tokens: list[str] = []
    seen: set[str] = set()
    for word in re.findall(r"[A-Za-z0-9]{3,}", question):
        low = word.lower()
        if low not in seen:
            seen.add(low)
            tokens.append(low)
    for run in re.findall(r"[\u4e00-\u9fff]{3,}", question):
        cleaned = "".join(ch for ch in run if ch not in _CJK_STOPWORDS)
        for i in range(0, max(len(cleaned) - 2, 0)):
            piece = cleaned[i : i + 3]
            if piece and piece not in seen:
                seen.add(piece)
                tokens.append(piece)
    return tokens[:16]


def short_cjk_terms(question: str) -> list[str]:
    """短词（2 字）兜底：trigram 查不到，用 LIKE。"""
    terms = []
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", question):
        cleaned = "".join(ch for ch in run if ch not in _CJK_STOPWORDS)
        if 2 <= len(cleaned) <= 3:
            terms.append(cleaned)
    return terms[:6]


def search_blocks(
    db: Session,
    user_id: int,
    query: str,
    limit: int = _DEFAULT_LIMIT,
    task_id: int | None = None,
) -> list[dict]:
    """在该用户（可限定某篇）的段落里检索，返回带文件名与片段的结果。

    只返回**没被删、没被归档**的文献——回收站里的东西不该被 agent 当成"知识库"。
    """
    limit = max(1, min(int(limit or _DEFAULT_LIMIT), 20))
    scope_sql = (
        "JOIN tasks t ON t.id = tb.task_id "
        "WHERE t.user_id = :user_id "
        + _TRASH_SQL
        + "AND t.archived_at IS NULL "
    )
    params: dict = {"user_id": user_id, "limit": limit}
    if task_id is not None:
        scope_sql += "AND tb.task_id = :task_id "
        params["task_id"] = task_id

    tokens = query_tokens(query)
    if tokens:
        params["q"] = " OR ".join(f'"{token}"' for token in tokens)
        try:
            rows = db.execute(
                text(
                    "SELECT tb.task_id, t.filename, f.block_id, f.text, f.translated "
                    "FROM task_blocks_fts f "
                    "JOIN task_blocks tb ON tb.id = f.rowid "
                    + scope_sql
                    + "AND task_blocks_fts MATCH :q "
                    "ORDER BY bm25(task_blocks_fts) LIMIT :limit"
                ),
                params,
            ).all()
        except OperationalError:
            rows = []
        hits = [_hit(row) for row in rows]
        if hits:
            return hits

    terms = short_cjk_terms(query)
    if not terms:
        return []
    clauses = []
    for idx, term in enumerate(terms):
        key = f"p{idx}"
        params[key] = f"%{term}%"
        clauses.append(f"(tb.translated LIKE :{key} OR tb.text LIKE :{key})")
    rows = db.execute(
        text(
            "SELECT tb.task_id, t.filename, tb.block_id, tb.text, tb.translated "
            "FROM task_blocks tb "
            + scope_sql
            + "AND ("
            + " OR ".join(clauses)
            + ") LIMIT :limit"
        ),
        params,
    ).all()
    return [_hit(row) for row in rows]


def _hit(row) -> dict:
    task_id, filename, block_id, raw, translated = row
    text_value = (translated or raw or "").strip()
    return {
        "task_id": task_id,
        "filename": filename,
        "block_id": block_id,
        "snippet": text_value[:240],
    }


def blocks_of(
    db: Session, user_id: int, task_id: int, block_ids: list[str] | None = None
) -> list[dict]:
    """读某篇的段落（可指定 block_id 列表）。**只给本人的文献**。"""
    conditions = [Task.id == task_id, Task.user_id == user_id]
    if _HAS_TRASH:
        conditions.append(Task.deleted_at.is_(None))
    owned = db.scalar(select(Task.id).where(*conditions))
    if owned is None:
        return []
    stmt = select(TaskBlock).where(TaskBlock.task_id == task_id).order_by(TaskBlock.id)
    rows = db.scalars(stmt).all()
    if block_ids:
        wanted = set(block_ids)
        rows = [row for row in rows if row.block_id in wanted]
    return [
        {
            "block_id": row.block_id,
            "text": (row.translated or row.text or "").strip(),
        }
        for row in rows
    ]
