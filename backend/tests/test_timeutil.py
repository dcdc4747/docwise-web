"""时间口径的单测（见 `app/timeutil.py`）。

这个模块小，但它修的是一个**用户看得见的 bug**：库里的时间戳原来两种口径并存
（`created_at` 是 SQLite `func.now()`＝UTC，`started_at`/`finished_at` 是 Python
`datetime.now()`＝本机本地），接口又不带时区输出，前端 `new Date()` 按本地解析
→ 列表页"上传时间"整体差一个时区（实测刚上传 20 分钟的文献显示「8 小时前」）。

所以这里钉两件事：① 写库统一 UTC（naive）；② 输出一定**带时区**。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from fastapi.testclient import TestClient
from helpers import TEST_USER_ID

from app.db import SessionLocal
from app.main import app
from app.models import Task
from app.timeutil import iso_utc, utc_now


def test_utc_now_is_naive_and_actually_utc() -> None:
    now = utc_now()
    assert now.tzinfo is None  # 与 SQLite func.now() 同口径（naive）
    delta = abs((now - datetime.now(UTC).replace(tzinfo=None)).total_seconds())
    assert delta < 5


def test_iso_utc_marks_naive_as_utc_and_keeps_the_instant() -> None:
    # 库里存的就是 UTC 墙钟，输出必须补上时区，否则前端按本地解析 → 整体偏一个时区
    assert iso_utc(datetime(2026, 9, 30, 19, 40, 10)) == "2026-09-30T19:40:10+00:00"
    assert iso_utc(None) is None


def test_iso_utc_converts_aware_values_to_utc() -> None:
    # 已是 aware 的值（auth 那几张表写的是 datetime.now(UTC)）照样给出绝对时刻
    beijing = timezone(timedelta(hours=8))
    assert iso_utc(datetime(2026, 10, 1, 3, 40, 10, tzinfo=beijing)) == (
        "2026-09-30T19:40:10+00:00"
    )


def test_task_api_serializes_timestamps_with_timezone() -> None:
    """接口出去的时间戳必须**带时区**——这是前端"多久以前"算得对的前提。"""
    started = datetime(2026, 9, 30, 19, 0, 0)
    finished = datetime(2026, 9, 30, 19, 5, 0)
    with TestClient(app) as client:
        with SessionLocal() as session:
            task = Task(
                user_id=TEST_USER_ID,
                filename="tz.pdf",
                status="completed",
                started_at=started,
                finished_at=finished,
            )
            session.add(task)
            session.commit()
            task_id = task.id

        res = client.get(f"/api/tasks/{task_id}")

    assert res.status_code == 200
    data = res.json()
    assert data["created_at"].endswith("+00:00")  # 库里是 func.now()（UTC）
    assert data["started_at"] == "2026-09-30T19:00:00+00:00"
    assert data["finished_at"] == "2026-09-30T19:05:00+00:00"
    # 已耗时是差值，跟着一起对（300 秒）
    assert data["elapsed_seconds"] == 300.0
