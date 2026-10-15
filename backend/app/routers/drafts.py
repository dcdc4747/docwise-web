"""起草与引文（M3 / 契约 §2.6 的 N18–N21，共 9 个端点）。

设计口径（照契约，别自己发明）：

- **草稿只存当前稿**，不建版本历史表（契约 §5 明写"别预建"）。
- ⭐ **引文插入时就生成并落库 CSL-JSON**（`citations.csl_json`）—— 它是 M4 格式检查的
  **唯一输入**（形态 §3.3："输入就是我们插入引文生成的 CSL-JSON，
  不接 Word、不做版面分析"）。
- ⭐ **"点 `[1]` 回原文高亮"不在本模块**：引文只回 `material_id`，由前端拿素材卡的
  `task_id` / `block_id` 去回跳；**源文献已删（`task_id` 为 null）时
  界面要如实说"仅存快照"**。
- 归属：所有"按草稿/按素材"的接口都要校验**属于当前账号**，
  非本人一律 404（不暴露"存在但无权限"）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db
from ..models import Citation, Draft, Material, User
from ..timeutil import iso_utc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/drafts", tags=["drafts"])

# 正文长度上限：够写长稿，又不至于让单行 JSON 撑爆（M4 的 doc_text 会整篇送检查）
_BODY_MAX = 200_000


# ============================================================ 序列化

def _serialize_citation(row: Citation) -> dict:
    """`Citation` 对象（契约 §2.6）：
    `{id, draft_id, material_id, order, csl_json, anchor}`。
    """
    return {
        "id": row.id,
        "draft_id": row.draft_id,
        "material_id": row.material_id,
        "order": row.order,
        "csl_json": row.csl_json,
        "anchor": row.anchor,
    }


def _serialize_draft(row: Draft, citations: list[Citation]) -> dict:
    """`Draft` 对象（契约 §2.6）：
    `{id, title, body_md, template_id, updated_at, citations[]}`。
    """
    return {
        "id": row.id,
        "title": row.title,
        "body_md": row.body_md,
        "template_id": row.template_id,
        "updated_at": iso_utc(row.updated_at),
        "citations": [_serialize_citation(item) for item in citations],
    }


# ============================================================ CSL-JSON（插入时生成）

def build_csl_json(material: Material) -> dict:
    """把素材卡快照转成 **CSL-JSON 1.0.2 单条 item**。

    ⚠️ **只写我们真有的字段**（材料诚实原则，别为了让 CSL 好看而编）：
    素材卡是"从文献里取出的证据快照"，四个深拷贝列是
    `text_quote` / `translated_quote` / `page` / `source_name`。所以：

    - `id` / `type` / `title` / `page` / `note` 用**真值**；
    - ⚠️ **`author` / `container-title` / `issued` / `DOI` 这些我们拿不到** ——
      一律**不写**（CSL 容许字段缺失，渲染器会按样式降级）。
      **绝不用"未知作者"这类占位串冒充数据** —— 那会让 M4 的格式检查拿到假字段。
    """
    item: dict = {
        "id": f"material-{material.id}",
        # 素材来自期刊论文（本项目只处理学术文献）；类型错了会让渲染器套错样式
        "type": "article-journal",
        "title": material.source_name,
        "page": str(material.page),
    }
    if material.note:
        item["note"] = material.note
    return item


# ============================================================ 请求体

class DraftCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    template_id: str | None = Field(default=None, max_length=64)


class DraftPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body_md: str | None = Field(default=None, max_length=_BODY_MAX)
    template_id: str | None = Field(default=None, max_length=64)


class Anchor(BaseModel):
    """文内插入位置。`block_id` 可空（素材来自已删文献时就没有块可锚）。"""

    block_id: str | None = Field(default=None, max_length=64)
    offset: int = Field(default=0, ge=0)


class CitationCreate(BaseModel):
    material_id: int
    anchor: Anchor = Field(default_factory=Anchor)


# ============================================================ 守门

def _load_owned_draft(db: Session, user: User, draft_id: int) -> Draft:
    """取自己的草稿；不存在或不是本人的 → 404（**不区分**，免得暴露"存在但无权限"）。"""
    row = db.scalar(
        select(Draft).where(Draft.id == draft_id, Draft.user_id == user.id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    return row


def _load_owned_material(db: Session, user: User, material_id: int) -> Material:
    """取自己的素材卡；**软删的不算**（`deleted_at` 非空视为已删）。"""
    row = db.scalar(
        select(Material).where(
            Material.id == material_id,
            Material.user_id == user.id,
            Material.deleted_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    return row


def _citations_of(db: Session, draft_id: int) -> list[Citation]:
    return list(
        db.scalars(
            select(Citation)
            .where(Citation.draft_id == draft_id)
            .order_by(Citation.order)
        ).all()
    )


# ============================================================ N18 列表 / 新建

@router.get("")
def list_drafts(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """`GET /api/drafts` → `200 {items: Draft[]}`（新的在前，各带自己的引文）。"""
    rows = db.scalars(
        select(Draft).where(Draft.user_id == user.id).order_by(Draft.updated_at.desc())
    ).all()
    return {"items": [_serialize_draft(row, _citations_of(db, row.id)) for row in rows]}


@router.post("", status_code=201)
def create_draft(
    body: DraftCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """`POST /api/drafts` → `201 Draft`。**起稿四入口**（模板 / 大纲 / 空白 / 上传模板）
    在界面上是四个按钮，落到这里只差 `template_id` 有没有值 ——
    本期只存标识、不做模板渲染。
    """
    row = Draft(
        user_id=user.id,
        title=body.title.strip(),
        body_md="",
        template_id=body.template_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize_draft(row, [])


# ============================================================ N19 单篇：读 / 改 / 删

@router.get("/{draft_id}")
def get_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """`GET /api/drafts/{id}` → `200 Draft`（带全部引文，刷新后回看用）。"""
    row = _load_owned_draft(db, user, draft_id)
    return _serialize_draft(row, _citations_of(db, row.id))


@router.patch("/{draft_id}")
def patch_draft(
    draft_id: int,
    body: DraftPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """`PATCH /api/drafts/{id}` → `200 Draft`。

    ⚠️ **只改传进来的字段**（`exclude_unset`）：`body_md=""` 是"清空正文"，
    与"没传正文"必须区分开 —— 用 `is not None` 判断会把清空吞掉。
    """
    row = _load_owned_draft(db, user, draft_id)
    patch = body.model_dump(exclude_unset=True)
    if "title" in patch and patch["title"] is not None:
        row.title = patch["title"].strip()
    if "body_md" in patch and patch["body_md"] is not None:
        row.body_md = patch["body_md"]
    if "template_id" in patch:
        row.template_id = patch["template_id"]
    db.commit()
    db.refresh(row)
    return _serialize_draft(row, _citations_of(db, row.id))


@router.delete("/{draft_id}")
def delete_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """`DELETE /api/drafts/{id}` → `200`。

    ⚠️ **SQLite 外键没开级联**（仓库既有坑）：删草稿必须**手工删它的引文**，
    否则 `citations` 会留下孤儿行，之后新建草稿拿到同一个 id 时编号会撞。
    """
    row = _load_owned_draft(db, user, draft_id)
    db.execute(delete(Citation).where(Citation.draft_id == row.id))
    db.delete(row)
    db.commit()
    return {"ok": True}


# ============================================================ N20 / N21 引文

@router.get("/{draft_id}/citations")
def list_citations(
    draft_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """`GET /api/drafts/{id}/citations` → `200 {items}`（每条带 `csl_json`）。"""
    row = _load_owned_draft(db, user, draft_id)
    return {"items": [_serialize_citation(item) for item in _citations_of(db, row.id)]}


@router.post("/{draft_id}/citations", status_code=201)
def create_citation(
    draft_id: int,
    body: CitationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """`POST /api/drafts/{id}/citations` → `201 Citation` ｜ 404 素材不存在。

    ⭐ 这是"读 → 写"的接缝：**素材卡是证据快照，引文是它在稿子里的落点**。
    - `order`（文内引用编号）由服务端算：**当前最大 +1** —— 编号连续性归服务端，
      前端自己数会在并发/删除后错位（M4 的格式检查第一条就查连续性）。
    - `csl_json` **在这里生成并落库**，之后渲染/改样式都不需要重算。
    """
    draft = _load_owned_draft(db, user, draft_id)
    material = _load_owned_material(db, user, body.material_id)

    next_order = (
        db.scalar(
            select(func.max(Citation.order)).where(Citation.draft_id == draft.id)
        )
        or 0
    ) + 1

    row = Citation(
        draft_id=draft.id,
        material_id=material.id,
        order=next_order,
        csl_json=build_csl_json(material),
        anchor=body.anchor.model_dump(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize_citation(row)


@router.delete("/{draft_id}/citations", status_code=200)
def clear_citations(
    draft_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """`DELETE /api/drafts/{id}/citations` → `200`（清空这篇稿的引文）。

    契约只给了一个"删"的路径（没有按 id 单删），所以这里是**整篇清空**。
    """
    row = _load_owned_draft(db, user, draft_id)
    db.execute(delete(Citation).where(Citation.draft_id == row.id))
    db.commit()
    return {"ok": True}
