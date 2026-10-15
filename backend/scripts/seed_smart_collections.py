"""给全部账号补齐**内置智能集合**三条（待读 / 在读 / 已读）。

## 什么时候要跑

契约说"内置三条随迁移种下"，而 `migrate_v2_schema.py` 只覆盖**迁移当时已存在**的
账号——后来注册的账号会一条都没有。`GET /api/smart-collections` 已经会**自愈**
（读之前缺哪条补哪条，见 `app/routers/smart_collections.py`），所以正常情况下
**不用手工跑**；这个脚本是给"一次性核对 / 补齐全部账号"的运维场景用的。

## 口径（照本仓迁移脚本惯例）

- **默认只预览**（打印将要补什么），加 `--apply` 才写；
- **幂等**：规则只有一份真源（`app/smart_rules.py`），缺哪条补哪条、齐了什么都不写；
- ⚠️ **故意不用 `_migration_marker`**：marker 是给"只能跑一次"的破坏性迁移用的
  （例如把历史时间戳减一个偏移，跑两次就减两次）。本脚本是**收敛型**的——
  新账号随时会出现，本来就该能反复跑。

## 用法（cwd = backend）

    .venv/Scripts/python -m scripts.seed_smart_collections           # 预览
    .venv/Scripts/python -m scripts.seed_smart_collections --apply   # 执行
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app import models  # noqa: E402,F401  (导入即把表结构注册进 Base.metadata)
from app.db import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402
from app.smart_rules import (  # noqa: E402
    BUILTIN_NAMES,
    ensure_builtins,
    missing_builtins,
)

_PREVIEW_LIMIT = 20


def main() -> int:
    parser = argparse.ArgumentParser(
        description="给全部账号补齐内置智能集合（默认只预览）"
    )
    parser.add_argument("--apply", action="store_true", help="真写库（默认只预览）")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        users = db.scalars(select(User).order_by(User.id)).all()
        todo = [
            (user.id, user.username, missing)
            for user in users
            if (missing := missing_builtins(db, user))
        ]
        print(f"账号 {len(users)} 个，缺内置规则的 {len(todo)} 个：")
        for user_id, username, missing in todo[:_PREVIEW_LIMIT]:
            print(f"  #{user_id} {username}：缺 {'、'.join(missing)}")
        if len(todo) > _PREVIEW_LIMIT:
            print(f"  …（还有 {len(todo) - _PREVIEW_LIMIT} 个）")

        if not todo:
            print("都齐了，什么都不用做。")
            return 0
        if not args.apply:
            print(
                f"\n（预览模式，什么都没改。要真执行加 --apply：将在 {len(todo)} "
                f"个账号上补齐 {len(BUILTIN_NAMES)} 条内置规则里缺的那些）"
            )
            return 0

        filled = sum(len(ensure_builtins(db, user)) for user in users)
        print(f"\n✓ 补了 {filled} 条内置规则，覆盖 {len(todo)} 个账号。")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
