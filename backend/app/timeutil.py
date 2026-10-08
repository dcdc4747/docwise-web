"""时间口径：**库里一律存 UTC（naive），接口一律输出带时区的 UTC**。

为什么要有这个模块（2026-10-01 修的 bug）：库里的时间戳原来**两种口径并存**——

- `tasks.created_at` / `updated_at` 等是 SQLite 的 `func.now()`，**UTC**；
- `tasks.started_at` / `finished_at` 是 Python 的 `datetime.now()`，**本机本地时间**。

接口原来一律 `isoformat()` 输出**不带时区**的字符串，前端 `new Date(iso)` 按**本地**解析
→ `created_at` 那一路就整体差了 8 小时（实测：刚上传 20 分钟的文献，列表页显示
「8 小时前」；库里 `created_at='2026-09-30 19:40:10'`＝本地 03:40）。

口径定了就不再摇摆：**新写入一律用 `utc_now()`**（naive UTC，与 SQLite 的
`func.now()` 同一口径），**接口一律用 `iso_utc()` 输出带时区的 UTC**，
前端 `new Date()` 才解析得对。模块小但必须只有一处，免得又各写各的。

⚠️ 已存在的历史数据（2026-10-01 之前写入的 `started_at` / `finished_at`）仍是
**本机本地时间**——一次性迁移脚本见本地 `temp/fix_timestamps_utc.py`（不进仓库）。
"""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """当下（**UTC、naive**）——写库统一用它，别再写 `datetime.now()`。

    为什么去掉 tzinfo：列是 SQLAlchemy 的 `DateTime`（无时区），与 SQLite 的
    `func.now()`（UTC）保持同一口径；带 tzinfo 写进去在 SQLite 上一样按 UTC 墙钟存，
    但读出来是 naive，两种写法混用会让"读到的值到底是什么口径"变模糊。
    """
    return datetime.now(UTC).replace(tzinfo=None)


def iso_utc(value: datetime | None) -> str | None:
    """把库里的时间戳输出成**带时区的 UTC** ISO 串（`...T19:40:10+00:00`）。

    naive 值一律当 **UTC** 处理（库里的口径就是这样）；已是 aware 的值按它自己的时区
    折算成 UTC 再输出——两种输入都能给出"绝对时刻"，前端不用猜。
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()
