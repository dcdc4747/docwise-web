"""收口检查（M4 / 契约 §2.7 的 N22–N23 + N43，共 3 个端点）。

口径（照契约，别自己发明）：

- **N22** `POST /api/check` `{draft_id, doc_text}` → `200 CheckReport`
  —— 跑一遍 `app/check/engine.py` 的纯函数引擎，**把这次运行落库**（N23 要能回看）；
- **N23** `GET /api/check/{run_id}` → `200 CheckReport`（刷新后回看 / 导出用）；
- ⭐ **报告就是唯一的产出**：本模块**不替用户改稿**
  （形态 §3.3 ②"并列摆出两处，不自动改"），也不写回草稿——检查是"看"，不是"改"；
- ⭐ `unknown` 是一等公民：判不出语言/制式就在报告里明说，**不当成"没问题"**；
- 归属：草稿不是本人的、或报告不是本人的 → **一律 404**（不暴露"存在但无权限"）。
"""

from __future__ import annotations

import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..check.engine import run_check
from ..deps import get_current_user, get_db
from ..models import CheckRun, Citation, Draft, Material, TaskUnderstanding, User
from ..timeutil import iso_utc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/check", tags=["check"])

# 正文上限与起草那条一致（M4 的 doc_text 就是整篇稿子）
_DOC_MAX = 200_000
# 挑候选素材时最多看多少张卡：**只影响"建议引哪一条"的质量，不影响判不判**
_MATERIAL_SCAN = 200


class CheckRequest(BaseModel):
    """契约 §2.7 的入参：`{draft_id, doc_text}`。"""

    draft_id: int
    doc_text: str = Field(default="", max_length=_DOC_MAX)


def _load_owned_draft(db: Session, user: User, draft_id: int) -> Draft:
    """取自己的草稿；不存在或不是本人的 → 404（**不区分**，免得暴露"存在但无权限"）。"""
    row = db.scalar(select(Draft).where(Draft.id == draft_id, Draft.user_id == user.id))
    if row is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    return row


def _citations_of(db: Session, draft_id: int) -> list[dict]:
    """把引文摊成引擎要的形状（`order` + `csl_json` 就够——格式检查只认这个）。"""
    rows = db.scalars(
        select(Citation).where(Citation.draft_id == draft_id).order_by(Citation.order)
    ).all()
    return [{"order": row.order, "csl_json": row.csl_json} for row in rows]


def _materials_of(db: Session, user: User) -> list[dict]:
    """本人的素材卡（未软删的、新的在前）——**只用来挑"该引哪一条"**。"""
    rows = db.scalars(
        select(Material)
        .where(Material.user_id == user.id, Material.deleted_at.is_(None))
        .order_by(Material.created_at.desc())
        .limit(_MATERIAL_SCAN)
    ).all()
    return [
        {
            "id": row.id,
            "page": row.page,
            "text_quote": row.text_quote,
            "translated_quote": row.translated_quote,
        }
        for row in rows
    ]


def _terms_of(db: Session, user: User, draft_id: int) -> list[dict]:
    """**被引文献**的术语表，摊平成 `{term, cn, source_name, task_id}`（给 R6 用）。

    取法：草稿的引文 → `Citation.material_id` → `Material.task_id` → 那些任务的
    `task_understanding.terms_json`。

    ⚠️ 两条口径：
    - `source_name` 用**素材快照里的**那一份（M2 口径：素材卡是快照）：
      **不 JOIN `tasks`** —— 源文献删了名字还在（快照的意义）；
    - `task_id` 为 null（源文献已删）就取不到术语表，那就**不比**（如实记账）。
    """
    rows = db.execute(
        select(
            Material.task_id, Material.source_name, TaskUnderstanding.terms_json
        )
        .join(Citation, Citation.material_id == Material.id)
        .join(TaskUnderstanding, TaskUnderstanding.task_id == Material.task_id)
        .where(
            Citation.draft_id == draft_id,
            Material.user_id == user.id,
            Material.task_id.is_not(None),
        )
    ).all()

    out: list[dict] = []
    for task_id, source_name, terms_json in rows:
        if not terms_json:
            continue
        try:
            items = json.loads(terms_json)
        except (TypeError, ValueError):
            # 理解层写坏了一条不该让整次检查失败 —— 跳过它，少比一篇
            continue
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                out.append(
                    {
                        "term": item.get("term"),
                        "cn": item.get("cn"),
                        "source_name": source_name,
                        "task_id": task_id,
                    }
                )
    return out


@router.post("")
def create_check(
    body: CheckRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """`POST /api/check` → `200 CheckReport` ｜ 404 草稿不存在。

    ⚠️ 正文取**请求体里的 `doc_text`**（契约如此），不读库里的 `body_md`：
    前端可能带着"还没保存的当前稿"来检查，服务端替它决定用哪一份才是错的。
    """
    _load_owned_draft(db, user, body.draft_id)
    report = run_check(
        body.doc_text,
        citations=_citations_of(db, body.draft_id),
        materials=_materials_of(db, user),
        terms=_terms_of(db, user, body.draft_id),
    )

    row = CheckRun(
        user_id=user.id,
        draft_id=body.draft_id,
        lang=report["step"]["lang"],
        citation_style=report["step"]["citation_style"],
        ruleset_version=report["ruleset_version"],
        report=report,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    # 落库之后才知道 run_id：把同一份报告补上它再存一次，
    # 这样 **GET 回来的和 POST 当场返回的逐字节一致**（两份不一致比没有更糟）。
    report["run_id"] = row.id
    row.report = report
    db.add(row)
    db.commit()
    return report


@router.get("/{run_id}")
def get_check(
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """`GET /api/check/{run_id}` → `200 CheckReport`（回看 / 导出）｜ 404。"""
    row = db.scalar(
        select(CheckRun).where(CheckRun.id == run_id, CheckRun.user_id == user.id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="检查报告不存在")
    return row.report


@router.get("")
def list_checks(
    draft_id: Annotated[int | None, Query()] = None,
    limit: Annotated[int, Query()] = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """`GET /api/check?draft_id?&limit?` → `{items: [...]}`｜N43 检查历史。

    ⚠️ **只列自己的**（按 `user_id` 过滤），与全站"别人的一律当不存在"同一条口径。
    ⚠️ 每条只带**摘要**（`summary.reported/unknown` + 语言 / 制式 / 规则版本 / 时间），
    要看逐条明细就点进去走 N23（`GET /api/check/{run_id}`）——
    **列表里塞整份报告**会让历史一多就拖死，而且报告形状本来就该只有一处定义。
    """
    size = max(1, min(int(limit), 50))
    stmt = select(CheckRun).where(CheckRun.user_id == user.id)
    if draft_id is not None:
        stmt = stmt.where(CheckRun.draft_id == draft_id)
    rows = db.scalars(stmt.order_by(CheckRun.id.desc()).limit(size)).all()

    items = []
    for row in rows:
        report = row.report or {}
        summary = report.get("summary") or {}
        step = report.get("step") or {}
        items.append(
            {
                "id": row.id,
                "draft_id": row.draft_id,
                "lang": row.lang,
                "citation_style": row.citation_style,
                "ruleset_version": row.ruleset_version,
                "created_at": iso_utc(row.created_at),
                "summary": {
                    "reported": summary.get("reported"),
                    "unknown": summary.get("unknown"),
                },
                "step": {
                    "lang": step.get("lang"),
                    "citation_style": step.get("citation_style"),
                },
            }
        )
    return {"items": items}
