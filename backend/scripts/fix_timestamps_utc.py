"""一次性迁移：把历史行里**本机本地时间**写进去的时间戳改成 UTC（2026-10-01）。

背景（见 `app/timeutil.py`）：2026-10-01 之前，`tasks.started_at` / `finished_at` 是
Python 的 `datetime.now()` 写的（**本机本地时间**），而 `tasks.created_at` 是
SQLite 的 `func.now()`（**UTC**）——同一张表两种口径。接口那时又不带时区输出，
前端按本地解析，于是"上传时间"整体差一个时区。

现在代码统一成 UTC 了，但**已经写进库里的那些本地时间不会自己变**：迁移就是把
`created_at < 切换时刻` 的行，按"当时的本机时区"换算成 UTC。

安全约定：
- **默认只预览**（打印将要改哪些行、改成什么），加 `--apply` 才真写；
- 只认"切换时刻之前创建、且字段非空"的行（`created_at` 是可靠的 UTC 锚点）；
- 跑过一次会往 `_migration_marker` 记一笔，**重复跑直接拒绝**（防减两次偏移）；
- 迁移前后各打印几行对照，改了什么一眼可见。

用法：

    cd backend
    .venv/Scripts/python -m scripts.fix_timestamps_utc               # 预览
    .venv/Scripts/python -m scripts.fix_timestamps_utc --apply       # 执行

（`--offset-hours` 可显式指定当时的时区偏移，默认取运行这台机器当前的本地偏移——
本机一直是东八，实测库里那些值就是这个口径。）
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402

MARKER = "timestamps_to_utc_20261001"
# 切换时刻（UTC）：比它早创建的行，其 started_at / finished_at 是本地时间。
CUTOFF_UTC = datetime(2026, 10, 1, 0, 0, 0)


def _db_path() -> Path:
    url = settings.database_url
    raw = url.split("sqlite:///")[-1]
    path = Path(raw)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    return path


def _local_offset() -> timedelta:
    """本机当前相对 UTC 的偏移（东八 = +8h）。"""
    return datetime.now(UTC).astimezone().utcoffset() or timedelta(0)


def main() -> int:
    parser = argparse.ArgumentParser(description="把历史时间戳从本机本地时间迁到 UTC")
    parser.add_argument("--apply", action="store_true", help="真写库（默认只预览）")
    parser.add_argument(
        "--offset-hours",
        type=float,
        default=None,
        help="当时写库用的时区偏移（小时），默认取本机当前偏移",
    )
    args = parser.parse_args()

    offset = (
        timedelta(hours=args.offset_hours)
        if args.offset_hours is not None
        else _local_offset()
    )
    db = _db_path()
    print(f"数据库：{db}")
    print(f"偏移：{offset}（迁移＝减去它，把本地墙钟换成 UTC 墙钟）")
    print(f"切换时刻（UTC）：{CUTOFF_UTC}")

    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS _migration_marker "
        "(name TEXT PRIMARY KEY, done_at TEXT)"
    )
    done = conn.execute(
        "SELECT 1 FROM _migration_marker WHERE name=?", (MARKER,)
    ).fetchone()
    if done:
        print(f"\n✗ 这个迁移跑过了（_migration_marker 里有 {MARKER}）——不要重复跑。")
        return 1

    rows = conn.execute(
        "SELECT id, created_at, started_at, finished_at FROM tasks "
        "WHERE created_at < ? AND (started_at IS NOT NULL OR finished_at IS NOT NULL) "
        "ORDER BY id",
        (CUTOFF_UTC.strftime("%Y-%m-%d %H:%M:%S"),),
    ).fetchall()
    print(f"\n待迁移 {len(rows)} 行（只列前 5 行与前 3 行改后结果）：")
    for task_id, created, started, finished in rows[:5]:
        print(f"  任务 {task_id}｜created_at={created}（UTC，不动）")
        print(f"      started_at {started} → {_shift(started, offset)}")
        print(f"      finished_at {finished} → {_shift(finished, offset)}")

    if not args.apply:
        print("\n（预览模式，什么都没改。要真执行加 --apply）")
        return 0

    for task_id, _, started, finished in rows:
        conn.execute(
            "UPDATE tasks SET started_at=?, finished_at=? WHERE id=?",
            (_shift(started, offset), _shift(finished, offset), task_id),
        )
    conn.execute(
        "INSERT INTO _migration_marker(name, done_at) VALUES (?, ?)",
        (MARKER, datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")),
    )
    conn.commit()

    print(f"\n✓ 改了 {len(rows)} 行。改后前 3 行：")
    for row in conn.execute(
        "SELECT id, created_at, started_at, finished_at FROM tasks "
        "ORDER BY id DESC LIMIT 3"
    ):
        print(
            f"  任务 {row[0]}｜created_at={row[1]}｜"
            f"started_at={row[2]}｜finished_at={row[3]}"
        )
    conn.close()
    return 0


def _shift(value: str | None, offset: timedelta) -> str | None:
    """本地墙钟字符串 → UTC 墙钟字符串。

    保持 SQLite 那套写法：`YYYY-MM-DD HH:MM:SS[.ffffff]`（不带时区后缀）。
    """
    if not value:
        return None
    text = value.strip()
    if "." in text:
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f")
        return (parsed - offset).strftime("%Y-%m-%d %H:%M:%S.%f")
    parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    return (parsed - offset).strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    raise SystemExit(main())
