"""演示库策展（归档）的行为测试。

`archived_at` 非空 = 列表里不显示，**但数据不删**：
详情 / 下载 / 问答 / 出处回跳都不受影响。
这条边界必须钉住——把"藏"和"删"混起来，一次写错的列表查询就会让人以为文献丢了。
"""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient
from helpers import TEST_USER_ID

from app.db import SessionLocal
from app.main import app
from app.models import Task


def test_archived_task_hidden_from_list_but_detail_still_works() -> None:
    with TestClient(app) as client:
        with SessionLocal() as session:
            visible = Task(
                user_id=TEST_USER_ID, filename="visible.pdf", status="completed"
            )
            hidden = Task(
                user_id=TEST_USER_ID,
                filename="hidden.pdf",
                status="completed",
                # 归档时间按 UTC 存（口径见 app/timeutil.py）
                archived_at=datetime(2026, 10, 8, 9, 0, 0),
            )
            session.add_all([visible, hidden])
            session.commit()
            visible_id, hidden_id = visible.id, hidden.id

        rows = client.get("/api/tasks").json()

    listed = {row["id"] for row in rows}
    assert visible_id in listed
    assert hidden_id not in listed

    # 藏 ≠ 删：详情照旧能取（所以下载产物、追问、从出处回跳都不受影响）
    with TestClient(app) as client:
        assert client.get(f"/api/tasks/{hidden_id}").status_code == 200
