"""论文问答（M4）：全量入上下文 + FTS5 词法检索超阈值兜底。

主路径：整篇译文（带 block_id 标记）塞给 DeepSeek，回答按 block_id 引用出处；
长度/噪声超阈值（`docwise_ask_full_context_max_chars`）时降级为 FTS5 召回 Top-N 块再答；
FTS 也召不回 → 诚实兜底（不调 LLM，不编造）。不建向量库。
"""

from __future__ import annotations

import re
from sqlite3 import OperationalError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..deps import get_db, settings
from ..llm import answer_question
from ..models import Task, TaskBlock

router = APIRouter(prefix="/api/tasks", tags=["ask"])

_FTS_LIMIT = 8
_FTS_MAX_TOKENS = 16
# CJK 常用虚词/代词：检索时滤掉，避免命中噪声
_CJK_STOPWORDS = set("的了吗呢么吧啊呀这那我你他她它在是有和与或就不都也很")

_HONEST_NO_HIT = "抱歉，在这篇论文的文本里没有找到与这个问题相关的内容。"


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


def _query_tokens(question: str) -> list[str]:
    """把问题转成 trigram 兼容的检索词：

    - ASCII 词（≥3 字符）原样（trigram 下即子串匹配）；
    - CJK 连续段去掉虚词后滑窗取 3 字（trigram 最少 3 字符，2 字查不到）。
    全部去重、限量；token 只含 [A-Za-z0-9] 与汉字，无注入风险。
    """
    tokens: list[str] = []
    seen: set[str] = set()
    for word in re.findall(r"[A-Za-z0-9]{3,}", question):
        low = word.lower()
        if low not in seen:
            seen.add(low)
            tokens.append(low)
    for run in re.findall(r"[\u4e00-\u9fff]+", question):
        cleaned = "".join(c for c in run if c not in _CJK_STOPWORDS)
        for i in range(len(cleaned) - 2):
            window = cleaned[i : i + 3]
            if window not in seen:
                seen.add(window)
                tokens.append(window)
    return tokens[:_FTS_MAX_TOKENS]


def _short_cjk_terms(question: str) -> list[str]:
    """CJK 二字滑窗（去虚词、去重、限量）——trigram 查不了 2 字词，
    用它做 LIKE 词法扫描兜底（如"方法"也能召回）。"""
    terms: list[str] = []
    seen: set[str] = set()
    for run in re.findall(r"[\u4e00-\u9fff]+", question):
        cleaned = "".join(c for c in run if c not in _CJK_STOPWORDS)
        for i in range(len(cleaned) - 1):
            term = cleaned[i : i + 2]
            if term not in seen:
                seen.add(term)
                terms.append(term)
    return terms[:_FTS_MAX_TOKENS]


def _fts_search(db: Session, question: str) -> list[tuple[str, str]]:
    """FTS5（trigram）词法召回 (block_id, text)；索引未就绪时安全降级为空。"""
    tokens = _query_tokens(question)
    if tokens:
        match = " OR ".join(f'"{token}"' for token in tokens)
        try:
            rows = db.execute(
                text(
                    "SELECT block_id, text, translated FROM task_blocks_fts "
                    "WHERE task_blocks_fts MATCH :q "
                    "ORDER BY bm25(task_blocks_fts) LIMIT :limit"
                ),
                {"q": match, "limit": _FTS_LIMIT},
            ).all()
        except OperationalError:
            rows = []
        hits = [(row[0], row[2] or row[1]) for row in rows]
        if hits:
            return hits

    # trigram 最少 3 字符：对短词（2 字滑窗）做 LIKE 词法扫描兜底
    terms = _short_cjk_terms(question)
    if not terms:
        return []
    clauses = []
    params: dict = {"limit": _FTS_LIMIT}
    for idx, term in enumerate(terms):
        key = f"p{idx}"
        params[key] = f"%{term}%"
        clauses.append(f"(translated LIKE :{key} OR text LIKE :{key})")
    rows = db.execute(
        text(
            "SELECT block_id, text, translated FROM task_blocks "
            f"WHERE {' OR '.join(clauses)} LIMIT :limit"
        ),
        params,
    ).all()
    return [(row[0], row[2] or row[1]) for row in rows]


@router.post("/{task_id}/ask")
def ask_paper(task_id: int, body: AskRequest, db: Session = Depends(get_db)):
    """回答论文问题：全量入上下文（超阈值则 FTS 兜底），回答带 block_id 出处。"""
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")

    blocks = db.scalars(
        select(TaskBlock).where(TaskBlock.task_id == task_id).order_by(TaskBlock.id)
    ).all()
    items = [
        (b.block_id, b.translated or b.text)
        for b in blocks
        if (b.translated or b.text)
    ]
    if not items:
        raise HTTPException(status_code=400, detail="该任务没有可提问的文本")

    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    total_chars = sum(len(text) for _, text in items)
    if total_chars <= settings.docwise_ask_full_context_max_chars:
        result = answer_question(items, question)
        return {
            "answer": result["answer"],
            "source_block_ids": result["source_block_ids"],
            "mode": "full_context",
        }

    hits = _fts_search(db, question)
    if not hits:
        return {
            "answer": _HONEST_NO_HIT,
            "source_block_ids": [],
            "mode": "fts",
        }
    result = answer_question(hits, question)
    return {
        "answer": result["answer"],
        "source_block_ids": result["source_block_ids"],
        "mode": "fts",
    }
