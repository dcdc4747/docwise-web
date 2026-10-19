"""草稿导出：Markdown 与 Word（.docx）。

两个端点都挂在 `/api/drafts/{draft_id}/export.*`：

- `GET /api/drafts/{draft_id}/export.md` → `text/markdown` 附件；
- `GET /api/drafts/{draft_id}/export.docx` → docx 附件（引擎不可用时 503）。

归属口径与 `routers/drafts.py` **完全一致**（直接复用它的私有查询函数）：
只认自己的草稿，非本人一律 **404**——不暴露"存在但无权限"。

⚠️ **.docx 不靠后端依赖**：`python-docx` 不在后端那几个包里，
所以借引擎环境的解释器（`DOCWISE_ENGINE_PYTHON`）生成，逻辑见
`services/draft_export.py`。引擎侧不可用 → **503 + 人话**，**不返回半成品**。
"""

from __future__ import annotations

import logging
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db
from ..models import User
from ..services.draft_export import (
    DOCX_MEDIA_TYPE,
    docx_unavailable_detail,
    safe_filename,
    to_docx_bytes,
    to_markdown,
)
from .drafts import _citations_of, _load_owned_draft

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/drafts", tags=["draft-export"])

_MARKDOWN_MEDIA_TYPE = "text/markdown"


def _attachment(filename: str) -> str:
    """RFC 5987：中文 / 空格都百分号编码，浏览器才拿得到正确文件名。"""
    return f"attachment; filename*=UTF-8''{quote(filename, safe='')}"


@router.get("/{draft_id}/export.md")
def export_draft_markdown(
    draft_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> Response:
    """导出 Markdown：正文原样 + 末尾参考文献（没有引文就不加空标题）。"""
    draft = _load_owned_draft(db, user, draft_id)
    text = to_markdown(draft, _citations_of(db, draft.id))
    filename = safe_filename(draft.title, ".md")
    return Response(
        content=text,
        media_type=_MARKDOWN_MEDIA_TYPE,
        headers={"Content-Disposition": _attachment(filename)},
    )


@router.get("/{draft_id}/export.docx")
def export_draft_docx(
    draft_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> Response:
    """导出 Word：借引擎环境的 python-docx；不可用时如实 503。"""
    draft = _load_owned_draft(db, user, draft_id)
    citations = _citations_of(db, draft.id)
    data = to_docx_bytes(draft, citations)
    if data is None:
        raise HTTPException(status_code=503, detail=docx_unavailable_detail())
    filename = safe_filename(draft.title, ".docx")
    return Response(
        content=data,
        media_type=DOCX_MEDIA_TYPE,
        headers={"Content-Disposition": _attachment(filename)},
    )
