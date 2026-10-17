"""个人中心的数据面（契约 §2.8 / N24–N29，共 9 个端点）。

口径（照契约与设计规范，别自己发明）：

- **归属**：一律只读/只动当前账号；别人的会话一律 404（不暴露"存在但无权限"）。
- **不编数、不编时间**：磁盘占用是**真走一遍目录**量出来的；台账就是 `memory_events`
  那一份**真源**（N26 与 N17 **同源，不许做两份台账**）；没有的数据如实为空。
- ⚠️ **账号行必须从库里重新取**（`db.get(User, user.id)`）：当前用户对象在测试里是
  依赖覆盖注入的**游离实例**（不在 session 里），直接 `db.delete(user)` 或改它的字段
  会**静默不生效**——这类 bug 只有用例能挡住。
- 时间一律 `iso_utc()`（带时区），与全站口径一致。
- 导出：`?format=zip|md`。zip 里装的是**数据**（`data.json` / `ledger.csv` /
  `README.md`），**原始 PDF 不重复塞一份**（几百 MB 的包对谁都没用）——README 里写明。
  ⚠️ 本期在内存里组包（数据量是个人级）；真要导出到 GB 级，得换流式 zip，另开任务。
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import storage
from ..auth import MAX_SESSIONS_PER_USER
from ..config import settings
from ..deps import current_session_hash, get_current_user, get_db
from ..models import (
    AuthSession,
    AuthTicket,
    BlockEdit,
    BlockExposure,
    CheckRun,
    Citation,
    Collection,
    Draft,
    Material,
    MemoryEvent,
    SmartCollection,
    Tag,
    Task,
    TaskBlock,
    TaskCollection,
    TaskHistory,
    TaskTag,
    TaskUnderstanding,
    User,
    UserPrefs,
)
from ..timeutil import iso_utc, utc_now
from .auth import _serialize_user

router = APIRouter(prefix="/api/me", tags=["me"])

_DISPLAY_NAME_MAX = 64
_CSV_HEADER = "created_at,layer,stage,actor,tool,summary"
_MD_HEADER = ["| 时间 | 环节 | 数据流向 | 说明 |", "|---|---|---|---|"]


# ============================================================ 小工具


def _dir_bytes(root: Path) -> int:
    """走一遍目录量真实占用；量不出来的项**不计入**（不编数字）。"""
    if not root.exists():
        return 0
    total = 0
    for entry in root.rglob("*"):
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:
            continue
    return total


def _db_bytes() -> int:
    """库文件大小；用的不是本地 sqlite 文件就返回 0（**不猜**）。"""
    url = settings.database_url
    if not url.startswith("sqlite:///"):
        return 0
    path = Path(url[len("sqlite:///") :])
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def _session_view(row: AuthSession) -> dict:
    """与前端契约 mock 的会话形状逐字段对齐。"""
    return {
        "id": row.id,
        "created_at": iso_utc(row.created_at),
        "expires_at": iso_utc(row.expires_at),
        "last_seen_at": iso_utc(row.last_seen_at),
        "user_agent": row.user_agent,
    }


def _memory_event_view(row: MemoryEvent) -> dict:
    """台账一行（N17 实现时**必须复用**这个形状，别写第二份）。"""
    return {
        "id": row.id,
        "task_id": row.task_id,
        "layer": row.layer,
        "stage": row.stage,
        "actor": row.actor,
        "tool": row.tool,
        "summary": row.summary,
        "payload": row.payload,
        "created_at": iso_utc(row.created_at),
    }


def _ledger_rows(db: Session, user_id: int) -> list[MemoryEvent]:
    """台账真源（新的在前；`id` 兜同秒的先后，保证顺序稳定）。"""
    return list(
        db.scalars(
            select(MemoryEvent)
            .where(MemoryEvent.user_id == user_id)
            .order_by(MemoryEvent.created_at.desc(), MemoryEvent.id.desc())
        ).all()
    )


def _csv_cell(value: object) -> str:
    """RFC4180：一律加引号、内部引号翻倍——逗号/引号/换行都撑不破表格。"""
    return '"' + str(value if value is not None else "").replace('"', '""') + '"'


def _ledger_csv(rows: list[MemoryEvent]) -> str:
    lines = [_CSV_HEADER]
    for row in rows:
        lines.append(
            ",".join(
                _csv_cell(cell)
                for cell in (
                    iso_utc(row.created_at),
                    row.layer,
                    row.stage,
                    row.actor,
                    row.tool,
                    row.summary,
                )
            )
        )
    return "\n".join(lines) + "\n"


def _md_cell(value: object) -> str:
    """表格里的 `|` 会切断列，转义掉；换行压成空格（Markdown 表格不支持多行）。"""
    return " ".join(str(value if value is not None else "").replace("|", "\\|").split())


def _ledger_markdown(rows: list[MemoryEvent]) -> str:
    lines = list(_MD_HEADER)
    for row in rows:
        lines.append(
            f"| {_md_cell(iso_utc(row.created_at))} | {_md_cell(row.stage)} "
            f"| {_md_cell(row.actor)} | {_md_cell(row.summary)} |"
        )
    return "\n".join(lines) + "\n"


def _attachment(content: str | bytes, media_type: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _require_self(db: Session, user: User) -> User:
    """把当前账号行**从库里重新取出来**（见模块文档：注入的可能是游离实例）。"""
    row = db.get(User, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    return row


# ============================================================ N24 磁盘占用


@router.get("/storage")
def my_storage(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """N24 磁盘占用分类。

    ⚠️ 这是**本服务数据目录**的占用（`uploads` / `outputs` / `backups` / `db`），
    **不按账号拆分**——备份与数据库本来就是整库级的东西，拆出来的数字只会是假的。
    """
    by_kind = {
        "uploads": _dir_bytes(storage.UPLOADS_DIR),
        "outputs": _dir_bytes(storage.OUTPUTS_DIR),
        "backups": _dir_bytes(storage.BACKUPS_DIR),
        "db": _db_bytes(),
    }
    return {
        "total_bytes": sum(by_kind.values()),
        "by_kind": by_kind,
        "location": str(storage.DATA_DIR),
    }


# ============================================================ N26 台账


@router.get("/ledger")
def my_ledger(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    format: Annotated[str, Query()] = "json",
):
    """N26 AI 使用台账导出（`json` / `csv` / `md`）。

    数据源就是 `memory_events`（与 N17 同源）；**别的值一律 400**，不静默回落成 json
    ——那会让人以为"导出了"，其实拿到的是另一种东西。
    """
    rows = _ledger_rows(db, user.id)
    if format == "json":
        return {"items": [_memory_event_view(row) for row in rows]}
    if format == "csv":
        return _attachment(
            _ledger_csv(rows), "text/csv; charset=utf-8", "docwise-ledger.csv"
        )
    if format == "md":
        return _attachment(
            _ledger_markdown(rows),
            "text/markdown; charset=utf-8",
            "docwise-ledger.md",
        )
    raise HTTPException(status_code=400, detail="format 只支持 json / csv / md")


# ============================================================ N25 一键导出


def _count(db: Session, model, user_id: int) -> int:
    """某个"挂 user_id 的表"里属于该账号的行数（导出摘要用，**数字来自库**）。"""
    stmt = select(func.count()).select_from(model).where(model.user_id == user_id)
    return int(db.scalar(stmt) or 0)


def _my_tasks(db: Session, user_id: int) -> list[Task]:
    return list(db.scalars(select(Task).where(Task.user_id == user_id)).all())


def _export_payload(db: Session, user: User) -> dict:
    """整账号的数据快照（**只含数据，不含 PDF 二进制**）。"""
    user_id = user.id
    tasks = _my_tasks(db, user_id)
    task_ids = [row.id for row in tasks]
    blocks = (
        list(db.scalars(select(TaskBlock).where(TaskBlock.task_id.in_(task_ids))).all())
        if task_ids
        else []
    )
    understanding = (
        list(
            db.scalars(
                select(TaskUnderstanding).where(
                    TaskUnderstanding.task_id.in_(task_ids)
                )
            ).all()
        )
        if task_ids
        else []
    )
    return {
        "exported_at": iso_utc(utc_now()),
        "account": {"id": user_id, "username": user.username},
        "tasks": [
            {
                "id": row.id,
                "filename": row.filename,
                "status": row.status,
                "tier": row.tier,
                "source_lang": row.source_lang,
                "target_lang": row.target_lang,
                "text_source": row.text_source,
                "reading_status": row.reading_status,
                "last_read_page": row.last_read_page,
                "created_at": iso_utc(row.created_at),
                "finished_at": iso_utc(row.finished_at),
                "archived_at": iso_utc(row.archived_at),
            }
            for row in tasks
        ],
        "task_blocks": [
            {
                "task_id": row.task_id,
                "block_id": row.block_id,
                "text": row.text,
                "translated": row.translated,
                "status": row.status.value,
                "error": row.error,
            }
            for row in blocks
        ],
        "task_understanding": [
            {
                "task_id": row.task_id,
                "status": row.status,
                "guide_json": row.guide_json,
                "terms_json": row.terms_json,
            }
            for row in understanding
        ],
        "materials": [
            {
                "id": row.id,
                "task_id": row.task_id,
                "block_id": row.block_id,
                "text_quote": row.text_quote,
                "translated_quote": row.translated_quote,
                "page": row.page,
                "source_name": row.source_name,
                "note": row.note,
                "deleted_at": iso_utc(row.deleted_at),
                "created_at": iso_utc(row.created_at),
            }
            for row in db.scalars(
                select(Material).where(Material.user_id == user_id)
            ).all()
        ],
        "drafts": [
            {
                "id": row.id,
                "title": row.title,
                "body_md": row.body_md,
                "template_id": row.template_id,
                "created_at": iso_utc(row.created_at),
                "updated_at": iso_utc(row.updated_at),
            }
            for row in db.scalars(select(Draft).where(Draft.user_id == user_id)).all()
        ],
        "citations": [
            {
                "id": row.id,
                "draft_id": row.draft_id,
                "material_id": row.material_id,
                "order": row.order,
                "csl_json": row.csl_json,
            }
            for row in db.scalars(
                select(Citation)
                .join(Draft, Draft.id == Citation.draft_id)
                .where(Draft.user_id == user_id)
            ).all()
        ],
        "check_runs": [
            {
                "id": row.id,
                "draft_id": row.draft_id,
                "lang": row.lang,
                "citation_style": row.citation_style,
                "ruleset_version": row.ruleset_version,
                "report": row.report,
                "created_at": iso_utc(row.created_at),
            }
            for row in db.scalars(
                select(CheckRun).where(CheckRun.user_id == user_id)
            ).all()
        ],
        "memory_events": [_memory_event_view(row) for row in _ledger_rows(db, user_id)],
        "collections": [
            {
                "id": row.id,
                "name": row.name,
                "parent_id": row.parent_id,
                "sort": row.sort,
            }
            for row in db.scalars(
                select(Collection).where(Collection.user_id == user_id)
            ).all()
        ],
        "tags": [
            {"id": row.id, "name": row.name, "kind": row.kind}
            for row in db.scalars(select(Tag).where(Tag.user_id == user_id)).all()
        ],
        "smart_collections": [
            {"id": row.id, "name": row.name, "query": row.query}
            for row in db.scalars(
                select(SmartCollection).where(SmartCollection.user_id == user_id)
            ).all()
        ],
        "block_edits": [
            {
                "task_id": row.task_id,
                "block_id": row.block_id,
                "before": row.before,
                "after": row.after,
                "created_at": iso_utc(row.created_at),
            }
            for row in db.scalars(
                select(BlockEdit).where(BlockEdit.user_id == user_id)
            ).all()
        ],
    }


def _export_markdown(db: Session, user: User) -> str:
    """导出摘要（**数字全部来自库**，不写"若干"）。"""
    tasks = len(_my_tasks(db, user.id))
    materials = _count(db, Material, user.id)
    drafts = _count(db, Draft, user.id)
    checks = _count(db, CheckRun, user.id)
    events = _count(db, MemoryEvent, user.id)
    return "\n".join(
        [
            f"# docwise 数据导出（{user.username}）",
            "",
            f"- 导出时间：{iso_utc(utc_now())}",
            f"- 文献：{tasks} 篇",
            f"- 素材卡：{materials} 条",
            f"- 草稿：{drafts} 篇",
            f"- 收口检查：{checks} 次",
            f"- AI 台账：{events} 条",
            "",
            "⚠️ 这份 Markdown 只是**摘要**：完整数据（块级原文/译文、引文、",
            "检查报告、台账）都在 `?format=zip` 的包里。",
            "⚠️ **原始 PDF 不在包内**：它们仍在 `data/uploads/` 下自行拷贝。",
            "⚠️ AI 台账单独导出：`GET /api/me/ledger?format=csv|md`。",
        ]
    ) + "\n"


def _export_readme() -> str:
    return "\n".join(
        [
            "# docwise 数据导出包",
            "",
            "- `data.json`：账号下全部数据（文献与块级原文/译文、素材卡、",
            "  草稿与引文、收口检查报告、AI 台账、集合与标签、人改留痕）。",
            "- `ledger.csv`：AI 使用台账（与 `data.json` 里的 `memory_events` 同源）。",
            "",
            "⚠️ **原始 PDF 不在这个包里**（它们仍在 `data/uploads/` 下）。",
            "⚠️ 台账里的 `actor` 就是数据流向的证据：`local` = 本地完成",
            "（取字 / 扫描件 OCR）；`api` = 发往云端模型服务（外文翻译 /",
            "扫件逐段翻译 / 导读 / 问答）。",
        ]
    ) + "\n"


@router.get("/export")
def export_all(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    format: Annotated[str, Query()] = "zip",
):
    """N25 一键导出：`?format=zip|md`（别的值 400）。"""
    if format == "md":
        return _attachment(
            _export_markdown(db, user),
            "text/markdown; charset=utf-8",
            "docwise-export.md",
        )
    if format != "zip":
        raise HTTPException(status_code=400, detail="format 只支持 zip / md")

    payload = _export_payload(db, user)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "data.json", json.dumps(payload, ensure_ascii=False, indent=2)
        )
        archive.writestr("ledger.csv", _ledger_csv(_ledger_rows(db, user.id)))
        archive.writestr("README.md", _export_readme())
    return _attachment(buffer.getvalue(), "application/zip", "docwise-export.zip")


# ============================================================ N29 会话


@router.get("/sessions")
def my_sessions(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """N29 登录设备与会话（**只列还能用的**，最近 20 台）。

    ⚠️ **上限 20**：每条会话在登录时插入、30 天才过期，实测一个账号能攒到 132 条；
    全量返回会让页面长到一屏放不下（用户截图报过）。
    ⭐ `current`：**哪台是你现在用的**——没有这个标记，"吊销"按钮长得全一样，
    很容易把自己踢下线（契约里原来没有这一列，本次显式追加）。
    """
    hash_now = current_session_hash(request)
    rows = db.scalars(
        select(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.expires_at > utc_now())
        .order_by(AuthSession.created_at.desc(), AuthSession.id.desc())
        .limit(MAX_SESSIONS_PER_USER)
    ).all()
    total = (
        db.scalar(
            select(func.count())
            .select_from(AuthSession)
            .where(AuthSession.user_id == user.id, AuthSession.expires_at > utc_now())
        )
        or 0
    )
    items = []
    for row in rows:
        view = _session_view(row)
        view["current"] = bool(hash_now) and row.token_hash == hash_now
        items.append(view)
    # 按**登录时间**新→旧，与表格第一列一致。
    # ⚠️ 别改成按最近活动排：那张表第一列是登录时间，按另一个字段排会让
    # 「18:58 排在 22:26 上面」看着像排序坏了（真踩过）。
    items.sort(key=lambda item: item["created_at"], reverse=True)
    return {"items": items, "total": int(total)}


@router.delete("/sessions/{session_id}")
def revoke_my_session(
    session_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """N29 逐个吊销。别人的会话 = 404（不暴露"存在但无权限"）。

    ⚠️ 吊销**当前正在用的这条**是允许的（那就是"退出登录"的效果），
    界面不做特殊标记——契约与 mock 里都没有"当前会话"这一列，不自己发明。
    """
    row = db.scalar(
        select(AuthSession).where(
            AuthSession.id == session_id, AuthSession.user_id == user.id
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    db.delete(row)
    db.commit()
    return {"deleted": True, "id": session_id}


# ============================================================ N28 / N27 账号


class MePatch(BaseModel):
    display_name: str | None = None


@router.patch("")
def update_me(
    payload: MePatch,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """N28 改显示名（1–64 字）。空 body = 什么都不改（幂等，不报错）。

    ⚠️ 显式传 `display_name: null` / 空串 → 400，与前端 mock 的口径一致。
    """
    row = _require_self(db, user)
    if "display_name" in payload.model_fields_set:
        name = (payload.display_name or "").strip()
        if not name or len(name) > _DISPLAY_NAME_MAX:
            raise HTTPException(status_code=400, detail="显示名要 1–64 个字")
        row.display_name = name
        db.commit()
        db.refresh(row)
    return _serialize_user(row)


@router.delete("")
def delete_me(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """N27 删除账号与全部数据（**不可逆**；二次确认在界面上，见 `MeView.vue`）。

    ⭐ 磁盘产物按任务逐个清（上传原件 + `outputs/{task_id}`），**不碰别人的任何东西**、
    也不动 `backups/`（整库级备份不属于某个账号）。
    """
    row = _require_self(db, user)
    user_id = row.id
    tasks = _my_tasks(db, user_id)
    file_paths = [
        (task.id, task.original_path, task.translated_path, task.dual_translated_path)
        for task in tasks
    ]
    task_ids = [task.id for task in tasks]

    # ⚠️ SQLite 外键没开级联：先删子表，再删任务与账号（顺序在这里写清楚，别靠运气）
    if task_ids:
        for model in (TaskBlock, TaskUnderstanding, TaskHistory):
            db.execute(delete(model).where(model.task_id.in_(task_ids)))
        db.execute(
            delete(TaskCollection).where(TaskCollection.task_id.in_(task_ids))
        )
        db.execute(delete(TaskTag).where(TaskTag.task_id.in_(task_ids)))
        db.execute(delete(AuthTicket).where(AuthTicket.task_id.in_(task_ids)))
    db.execute(delete(BlockEdit).where(BlockEdit.user_id == user_id))
    db.execute(delete(BlockExposure).where(BlockExposure.user_id == user_id))
    draft_ids = [
        draft_id
        for draft_id in db.scalars(
            select(Draft.id).where(Draft.user_id == user_id)
        ).all()
    ]
    if draft_ids:
        db.execute(delete(Citation).where(Citation.draft_id.in_(draft_ids)))
    db.execute(delete(CheckRun).where(CheckRun.user_id == user_id))
    db.execute(delete(Draft).where(Draft.user_id == user_id))
    db.execute(delete(Material).where(Material.user_id == user_id))
    db.execute(delete(MemoryEvent).where(MemoryEvent.user_id == user_id))
    # ⚠️ 偏好也要一起清：`user_prefs.user_id` 是 unique 的，
    # 留着就是一条永远对不上人的孤儿行
    db.execute(delete(UserPrefs).where(UserPrefs.user_id == user_id))
    db.execute(delete(Task).where(Task.user_id == user_id))
    db.execute(delete(Collection).where(Collection.user_id == user_id))
    db.execute(delete(Tag).where(Tag.user_id == user_id))
    db.execute(delete(SmartCollection).where(SmartCollection.user_id == user_id))
    db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
    db.execute(delete(AuthTicket).where(AuthTicket.user_id == user_id))
    db.delete(row)
    db.commit()

    for task_id, original, translated, dual in file_paths:
        storage.remove_task_files(task_id, original, translated, dual)
    return {"deleted": True, "id": user_id}

# ============================================================ 偏好（N40 / N41）


_PREF_MAX_CHARS = 8192
_PREF_MAX_KEYS = 32
_PREF_KEY_MAX = 64


class PrefsIn(BaseModel):
    """偏好整包（键值都是 JSON 标量）。"""

    prefs: dict[str, Any]


def _clean_prefs(raw: dict[str, Any]) -> dict[str, Any]:
    """校验并瘦身一份偏好包；不合格一律 **400 并说明为什么**（不静默丢字段）。

    判据（都很保守，因为这是"整包覆盖"，写坏了会连带别的偏好一起没）：
    - 键必须是 1–64 字的字符串、最多 32 个；
    - 值只能是 JSON 标量（bool / int / float / str / null）——**嵌套结构直接拒**，
      否则"整包存 JSON"迟早变成一个能塞任意东西的口袋；
    - 整个包序列化后不超过 8 KB。
    """
    if len(raw) > _PREF_MAX_KEYS:
        raise HTTPException(
            status_code=400, detail=f"偏好项太多（{len(raw)} > {_PREF_MAX_KEYS}）"
        )
    cleaned: dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key or len(key) > _PREF_KEY_MAX:
            raise HTTPException(status_code=400, detail="偏好名必须是 1–64 字的字符串")
        if value is not None and not isinstance(value, (bool, int, float, str)):
            raise HTTPException(
                status_code=400, detail=f"偏好 {key} 只能是标量（布尔/数字/文本）"
            )
        cleaned[key] = value
    size = len(json.dumps(cleaned, ensure_ascii=False))
    if size > _PREF_MAX_CHARS:
        raise HTTPException(
            status_code=400, detail=f"偏好包太大（{size} > {_PREF_MAX_CHARS} 字节）"
        )
    return cleaned


def _prefs_payload(row: UserPrefs | None) -> dict[str, Any]:
    """库里的 JSON 文本 → dict。**坏数据回空包**（不让一条脏记录把整页顶掉）。"""
    if row is None or not row.payload:
        return {}
    try:
        data = json.loads(row.payload)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


@router.get("/preferences")
def get_preferences(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """N40 取偏好。**没存过就回空包**（不是 404）——

    前端靠它判断"该不该把本机那份推上来"。
    """
    row = db.scalar(select(UserPrefs).where(UserPrefs.user_id == user.id))
    return {"prefs": _prefs_payload(row)}


@router.put("/preferences")
def put_preferences(
    payload: PrefsIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """N41 整包覆盖偏好（PUT 语义：没给的键就是不要了）。返回写进去的那份。

    ⚠️ **一个用户只有一行**（`user_id` unique）：有就改、没有就建，
    免得留下两行"谁的偏好算数"说不清。
    """
    cleaned = _clean_prefs(payload.prefs)
    row = db.scalar(select(UserPrefs).where(UserPrefs.user_id == user.id))
    text = json.dumps(cleaned, ensure_ascii=False, sort_keys=True)
    if row is None:
        row = UserPrefs(user_id=user.id, payload=text)
        db.add(row)
    else:
        row.payload = text
        row.updated_at = utc_now()
    db.commit()
    db.refresh(row)
    return {"prefs": _prefs_payload(row), "updated_at": iso_utc(row.updated_at)}
