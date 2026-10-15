"""内置智能集合（**规则即数据的唯一真源**）。

为什么要单独一个模块：同一份规则有**三处**要用到——

1. **数据迁移**（`scripts/migrate_v2_schema.py`）：给**已有**用户种下三条；
2. **`GET /api/smart-collections`**：给**后来注册**的用户补上（自愈，缺哪条补哪条）；
3. **运维脚本**（`scripts/seed_smart_collections.py`）：手工给全部账号补齐。

三处各写一份 = 早晚漂移，而漂移的后果很难看：界面上显示的那条规则，
和当初迁进去的那条不一样。所以规则表只在这里定义一次。

⚠️ 规则形状**冻结**在 `models.SmartCollection`：
`{"all": [{field, op, value}, …]}`，
`field ∈ {reading_status, tag, collection, native, text_source}`、
`op ∈ {eq, in, not_in}`。内置三条全是 `reading_status` 的等值判断——
**它们是"人的组织"，不是文献自己的属性**（所以规则读的是 `tasks.reading_status`
这一列，不是标签）。
"""

from __future__ import annotations

from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import SmartCollection, User
from .timeutil import utc_now

READING_STATUS_FIELD = "reading_status"


def reading_status_rule(value: str) -> dict:
    """`状态 = <value>` 这一条规则（三条内置规则共用同一个形状）。"""
    return {"all": [{"field": READING_STATUS_FIELD, "op": "eq", "value": value}]}


#: 内置三条（顺序即展示顺序，也写进 `sort`）
BUILTIN_SMART_COLLECTIONS: tuple[tuple[str, dict], ...] = (
    ("待读", reading_status_rule("todo")),
    ("在读", reading_status_rule("reading")),
    ("已读", reading_status_rule("done")),
)
BUILTIN_NAMES: tuple[str, ...] = tuple(name for name, _ in BUILTIN_SMART_COLLECTIONS)


def missing_builtins(db: Session, user: User) -> list[str]:
    """这个账号**还缺**哪几条内置规则（按名字判；已存在同名内置的算已有）。"""
    have = set(
        db.scalars(
            select(SmartCollection.name).where(
                SmartCollection.user_id == user.id, SmartCollection.builtin.is_(True)
            )
        ).all()
    )
    return [name for name in BUILTIN_NAMES if name not in have]


def ensure_builtins(db: Session, user: User) -> list[str]:
    """缺哪条补哪条，返回**本次补上**的名字。

    幂等：已经齐了就返回空表，**一次库都不写**（所以可以放在读接口里自愈）。
    """
    missing = missing_builtins(db, user)
    if not missing:
        return []
    now = utc_now()
    for name in missing:
        query = next(
            item for row_name, item in BUILTIN_SMART_COLLECTIONS if row_name == name
        )
        db.add(
            SmartCollection(
                user_id=user.id,
                name=name,
                # deepcopy：三条共用同一份结构时别让 JSON 序列化踩到共享对象
                query=deepcopy(query),
                builtin=True,
                sort=BUILTIN_NAMES.index(name),
                created_at=now,
            )
        )
    db.commit()
    return missing
