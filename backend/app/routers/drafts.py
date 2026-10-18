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

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db
from ..models import Citation, Draft, DraftVersion, Material, User
from ..timeutil import iso_utc, utc_now

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/drafts", tags=["drafts"])

# 正文长度上限：够写长稿，又不至于让单行 JSON 撑爆（M4 的 doc_text 会整篇送检查）
_BODY_MAX = 200_000
# HTML 比 Markdown 长不少（标签），给 2 倍余量
_HTML_MAX = _BODY_MAX * 2


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
    `{id, title, body_md, body_html, template_id, updated_at, citations[]}`。

    `body_html` 是富文本源（逐段字号/行距），`body_md` 是由它转出来的派生视图。
    """
    return {
        "id": row.id,
        "title": row.title,
        "body_md": row.body_md,
        "body_html": row.body_html,
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
    # 富文本源（2026-10-19）：编辑器是 TipTap，逐段字号只能在 HTML 里存
    body_html: str | None = Field(default=None, max_length=_HTML_MAX)
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
    body_changed = False
    if "body_md" in patch and patch["body_md"] is not None:
        # ⭐ 版本只在**正文内容真的变了**时才记（只改标题 / 连点保存不长版本）
        body_changed = patch["body_md"] != (row.body_md or "")
        row.body_md = patch["body_md"]
    if "body_html" in patch:
        # 富文本源跟着一起存；只传 html 不传 md 时，md 视为不变（老功能仍读 md）
        row.body_html = patch["body_html"]
    if "template_id" in patch:
        row.template_id = patch["template_id"]
    if body_changed:
        _record_version(db, row, source="user")
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
    # ⚠️ 和引文同一个坑：SQLite 外键没开级联，子表必须手工删，
    # 否则删掉最大 id 的那篇后新建草稿会复用同一个 id，把旧版本"继承"过来。
    db.execute(delete(DraftVersion).where(DraftVersion.draft_id == row.id))
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


# ============================================================ 版本历史（2026-10-19）
#
# 为什么现在才建这张表：**AI 能直接改稿之后，版本历史成了回滚的前提**。
# 用户要能回到"AI 动手之前"的那一版，而"AI 动了哪一版"没法从当前稿反推。
#
# 三条口径（别自己发明）：
# - **版本是整篇快照**，不是 diff：判据是"能不能一键回到那一版"，不是省空间；
# - **只在正文真变了时记**（`PATCH` 那条路）＋ 与上一条内容相同不重复记 ——
#   同一秒里连点保存会攒出一串一模一样的版本，把 50 版额度白白吃掉；
# - **回滚前先存当前稿**（`source="restore"`）：回滚本身也必须可撤销。

_VERSIONS_KEEP = 50
_VERSIONS_DEFAULT_LIMIT = 20
_VERSIONS_MAX_LIMIT = 100


def _serialize_version_summary(row: DraftVersion) -> dict:
    """列表项（**不带正文**）：`{id, source, note, created_at, chars}`。"""
    return {
        "id": row.id,
        "source": row.source,
        "note": row.note,
        "created_at": iso_utc(row.created_at),
        "chars": len(row.body_md or ""),
    }


def _serialize_version(row: DraftVersion) -> dict:
    """单版详情：`{id, body_md, title, source, created_at}`（**只读回显**）。"""
    return {
        "id": row.id,
        "body_md": row.body_md,
        "body_html": row.body_html,
        "title": row.title,
        "source": row.source,
        "created_at": iso_utc(row.created_at),
    }


def _trim_versions(db: Session, draft_id: int) -> None:
    """只留最近 `_VERSIONS_KEEP` 版。

    ⚠️ 排序键是 `id` 不是 `created_at`：同一秒里的多条 `created_at` 完全相同，
    按时间排等于没排（`id` 单调递增，才是真实的先后）。
    ⚠️ 删除与新增在**同一个事务**里（调用方 commit），不交给定期清理脚本 ——
    否则"上限 50"只是愿望，中间会有一段超额期。
    """
    stale = db.scalars(
        select(DraftVersion.id)
        .where(DraftVersion.draft_id == draft_id)
        .order_by(DraftVersion.id.desc())
        .offset(_VERSIONS_KEEP)
    ).all()
    if stale:
        db.execute(delete(DraftVersion).where(DraftVersion.id.in_(stale)))


def _record_version(
    db: Session,
    draft: Draft,
    *,
    source: str,
    note: str | None = None,
    dedupe: bool = True,
) -> DraftVersion | None:
    """给草稿记一版快照（并把表裁到最近 `_VERSIONS_KEEP` 版）。

    `dedupe=True`（`PATCH` 保存走这条）：**与上一条版本正文相同就不记** ——
    幂等规则，挡的是"同一份正文连点保存"攒出一串空壳版本。
    `dedupe=False`（回滚前的快照走这条）：**必须留痕**，哪怕与上一条内容相同；
    这条快照是"撤销这次回滚"的唯一凭据，省掉它就等于把中间稿弄丢了。

    返回新版本行；被幂等规则挡掉时返回 `None`（调用方不需要区分）。
    """
    body = draft.body_md or ""
    if dedupe:
        last = db.scalar(
            select(DraftVersion)
            .where(DraftVersion.draft_id == draft.id)
            .order_by(DraftVersion.id.desc())
            .limit(1)
        )
        if last is not None and (last.body_md or "") == body:
            return None

    row = DraftVersion(
        draft_id=draft.id,
        body_md=body,
        body_html=draft.body_html,
        title=draft.title or "",
        source=source,
        note=note,
        created_at=utc_now(),
    )
    db.add(row)
    db.flush()
    _trim_versions(db, draft.id)
    return row


def _load_owned_version(
    db: Session, user: User, draft_id: int, version_id: int
) -> tuple[Draft, DraftVersion]:
    """取"自己草稿的某一版"；草稿非本人、版本不存在、版本属于别的草稿 → 一律 404。"""
    draft = _load_owned_draft(db, user, draft_id)
    row = db.scalar(
        select(DraftVersion).where(
            DraftVersion.id == version_id,
            DraftVersion.draft_id == draft.id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="版本不存在")
    return draft, row


@router.get("/{draft_id}/versions")
def list_versions(
    draft_id: int,
    limit: int = Query(default=_VERSIONS_DEFAULT_LIMIT, ge=1, le=_VERSIONS_MAX_LIMIT),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """`GET /api/drafts/{id}/versions?limit=20` → `200 {items}`（新的在前）。

    ⚠️ **列表不返回正文**：正文单篇可达十几万字，20 条一起带出来会把
    "打开版本面板"变成一次大传输。列表只给 `chars` 让用户认得出是哪一版，
    要看正文点详情那一条。
    """
    draft = _load_owned_draft(db, user, draft_id)
    rows = db.scalars(
        select(DraftVersion)
        .where(DraftVersion.draft_id == draft.id)
        .order_by(DraftVersion.id.desc())
        .limit(limit)
    ).all()
    return {"items": [_serialize_version_summary(row) for row in rows]}


@router.get("/{draft_id}/versions/{version_id}")
def get_version(
    draft_id: int,
    version_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """`GET /api/drafts/{id}/versions/{version_id}` → `200 Version`。

    ⚠️ **只读回显，不自动应用**：用户点开某一版只是想看看当时写了什么，
    真回滚要走 `POST .../restore` —— 拿"点开"当"应用"会让误点直接改稿。
    """
    _, row = _load_owned_version(db, user, draft_id, version_id)
    return _serialize_version(row)


@router.post("/{draft_id}/versions/{version_id}/restore")
def restore_version(
    draft_id: int,
    version_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """`POST /api/drafts/{id}/versions/{version_id}/restore` → `200 Draft`。

    ⭐ **先把当前正文存成一版 `source="restore"`，再写回**：回滚是把稿子往回拨，
    如果不在拨之前留痕，"回滚"本身就成了不可撤销的操作 —— 那等于用一次误点
    换掉用户最新的稿子。
    ⚠️ 只写回**正文**（`body_md`）；`title` 进快照只是为了记录当时的标题，
    回滚不擅自改标题。
    """
    draft, row = _load_owned_version(db, user, draft_id, version_id)
    _record_version(db, draft, source="restore", dedupe=False)
    draft.body_md = row.body_md
    # 样式也要一起回来（只回 md 会让"回滚后字号全变默认"这种更迷惑）
    draft.body_html = row.body_html
    db.commit()
    db.refresh(draft)
    return _serialize_draft(draft, _citations_of(db, draft.id))
