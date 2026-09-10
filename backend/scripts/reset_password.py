"""管理员命令行工具：重置密码 / 提升管理员 / 列出账号。

用法（在 backend/ 目录下）：
    uv run python scripts/reset_password.py --list
    uv run python scripts/reset_password.py --user demo --password 新的密码
    uv run python scripts/reset_password.py --user demo --make-admin

说明：本项目不做邮箱找回密码，忘记密码就用本脚本（或管理后台）。
脚本只读写数据库，不启动 worker，也不会碰翻译任务。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.auth import hash_password, validate_password  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402


def _list_users() -> None:
    with SessionLocal() as session:
        users = session.scalars(select(User).order_by(User.id)).all()
    if not users:
        print("（暂无账号）")
        return
    print(f"{'ID':<4}{'用户名':<20}{'角色':<8}{'状态':<8}最后登录")
    for user in users:
        print(
            f"{user.id:<4}{user.username:<20}{user.role:<8}"
            f"{'启用' if user.is_active else '停用':<8}"
            f"{user.last_login_at or '—'}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="docwise 账号管理（本地运维）")
    parser.add_argument("--list", action="store_true", help="列出所有账号")
    parser.add_argument("--user", help="用户名")
    parser.add_argument("--password", help="设置新密码（至少 8 位）")
    parser.add_argument(
        "--make-admin", action="store_true", help="把该账号提升为管理员"
    )
    args = parser.parse_args()

    if args.list:
        _list_users()
        return 0

    if not args.user:
        parser.error("需要 --user（或使用 --list）")

    with SessionLocal() as session:
        user = session.scalars(select(User).where(User.username == args.user)).first()
        if user is None:
            print(f"账号不存在：{args.user}")
            return 1

        changed = False
        if args.password:
            if (error := validate_password(args.password)) is not None:
                print(error)
                return 1
            user.password_hash = hash_password(args.password)
            changed = True
            print(f"已重置 {user.username} 的密码")
        if args.make_admin:
            user.role = "admin"
            changed = True
            print(f"已把 {user.username} 设为管理员")

        if not changed:
            print("没有要做的改动：请给 --password 或 --make-admin")
            return 0

        session.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
