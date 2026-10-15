"""知识库 · 智能集合（契约 §2.3 的 N9–N11，共 3 个端点）。

⭐ **规则即数据**：`query` 形状**冻结**为 `{"all": [{field, op, value}, …]}`，
`field ∈ {reading_status, tag, collection, native, text_source}`、
`op ∈ {eq, in, not_in}`。
做成本行数据、而不是几个 `if` 的理由写在 `models.py` 的 `SmartCollection` 里
（判据不是"文献有多少篇"，而是"规则有多少条、规则是不是数据"）。

三条口径：

- **本期只做预置规则**（`builtin: true`：待读 / 在读 / 已读三条）——**不做**用户自定义
  查询构建器，但**接口形状照契约保留**，第二档（"把当前筛选存为智能集合"）以后 POST
  同一个端点、传序列化后的筛选即可；
- ⚠️ **三条内置规则的唯一真源是 `app/smart_rules.py`**（迁移脚本、本文件、
  运维脚本三处共用）：契约说"迁移时种下"，但迁移只覆盖**当时已存在**的账号——
  **后来注册的账号会一条都没有**。
  所以 N9 读之前先 `ensure_builtins()` **自愈**（缺哪条补哪条，齐了一次库都不写）；
- ⭐ **内置的不许删** → 400；
- ⭐ 计数**复用列表那套匹配**（`routers/tasks.py` 的 `_rule_context` /
  `_matches_smart_rule`）——**绝不在这里写第二套匹配逻辑**：一旦两套，
  界面上的"N 篇"和点进去看到的就会不一致。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db
from ..models import SmartCollection, Task, User
from ..smart_rules import ensure_builtins
from .tasks import _matches_smart_rule, _rule_context

router = APIRouter(prefix="/api/smart-collections", tags=["smart-collections"])

# 与前端 mock 逐字一致的三个白名单（契约 §2.3 冻结）
QUERY_FIELDS = ("reading_status", "tag", "collection", "native", "text_source")
QUERY_OPS = ("eq", "in", "not_in")
_NAME_MAX = 64
_BAD_QUERY = (
    "query 要是 {all: [{field, op, value}]}，"
    f"field ∈ {{{', '.join(QUERY_FIELDS)}}}，op ∈ {{{', '.join(QUERY_OPS)}}}"
)


def _clean_name(raw: object) -> str:
    name = str(raw or "").strip()
    if not name or len(name) > _NAME_MAX:
        raise HTTPException(status_code=400, detail="名字要 1–64 个字")
    return name


def query_is_valid(query: object) -> bool:
    """形状必须**非空**且每条都带 `value`（缺 `value` 的条件没有意义，宁可 400）。

    这条判据与前端 mock 的 `queryValid` 是同一套；`value` 用 `in` 判断而不是 `get`，
    是为了让 `{"value": null}` 这种"显式给了 null"也算给了。
    """
    conditions = (query or {}).get("all") if isinstance(query, dict) else None
    if not isinstance(conditions, list) or not conditions:
        return False
    for item in conditions:
        if not isinstance(item, dict):
            return False
        if item.get("field") not in QUERY_FIELDS or item.get("op") not in QUERY_OPS:
            return False
        if "value" not in item:
            return False
    return True


def _count(db: Session, user: User, query: dict) -> int:
    """按规则数"我的、且没归档的"文献（与 `GET /api/tasks?smart_id=` 同一套匹配）。"""
    rows = db.scalars(
        select(Task).where(Task.user_id == user.id, Task.archived_at.is_(None))
    ).all()
    context = _rule_context(db, [task.id for task in rows])
    return sum(1 for task in rows if _matches_smart_rule(task, query, context))


def _view(db: Session, user: User, row: SmartCollection) -> dict:
    """智能集合对象（契约 §2.3）：`{id, name, query, count, builtin}`。"""
    return {
        "id": row.id,
        "name": row.name,
        "query": row.query,
        "count": _count(db, user, row.query or {}),
        "builtin": bool(row.builtin),
    }


@router.get("")
def list_smart_collections(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """N9 智能集合列表（每条带 `count`，由规则当场算出来）。

    ⚠️ 读之前先 `ensure_builtins()`：迁移只覆盖**当时已存在**的账号，
    后来注册的账号一条内置规则都没有——自愈放在读接口里最省事，且它是幂等的。
    """
    ensure_builtins(db, user)
    rows = db.scalars(
        select(SmartCollection)
        .where(SmartCollection.user_id == user.id)
        .order_by(SmartCollection.builtin.desc(), SmartCollection.id)
    ).all()
    return {"items": [_view(db, user, row) for row in rows]}


class SmartCollectionIn(BaseModel):
    name: str
    # ⚠️ 故意用 `Any` 而不是 `dict`：写成 `dict` 时形状错的请求会被 pydantic
    # 先挡成 **422**，而契约（与前端 mock）要的是 **400** ——
    # 校验放我们自己手里，错误码才统一。
    query: Any


@router.post("", status_code=201)
def create_smart_collection(
    payload: SmartCollectionIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """N10 新建智能集合（用户自定义的，`builtin: false`）。

    400：名字不合法 / query 非法（形状与白名单见契约 §2.3）。
    """
    name = _clean_name(payload.name)
    if not query_is_valid(payload.query):
        raise HTTPException(status_code=400, detail=_BAD_QUERY)
    row = SmartCollection(
        user_id=user.id, name=name, query=payload.query, builtin=False
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _view(db, user, row)


@router.delete("/{smart_id}")
def delete_smart_collection(
    smart_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """N11 删除。⭐ **内置的不许删 → 400**；别人的与不存在的一律 404。"""
    row = db.scalar(
        select(SmartCollection).where(
            SmartCollection.id == smart_id, SmartCollection.user_id == user.id
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="智能集合不存在")
    if row.builtin:
        raise HTTPException(status_code=400, detail="内置规则不许删")
    db.delete(row)
    db.commit()
    return {"deleted": True, "id": smart_id}
