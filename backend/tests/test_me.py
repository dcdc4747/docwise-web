"""个人中心数据面（契约 §2.8 / N24–N29 ＋ N30 的追加字段）的测试。

盯四件事：

1. ⭐ **只自己的数据**：造第二个账号的数据，断言**看不见**（列表里没有、
   别人的会话 404）；
2. ⭐ **空数据时诚实**：没数据就是零/空表，**不编数**（磁盘占用是真量出来的）；
3. ⭐ **导出真能打开**：zip 真能解、JSON 真能解析、CSV 能被解析回**原样**、
   MD 不被 `|` 切断；
4. ⭐ **删账号真删干净、且不碰别人**（含磁盘产物）。

⚠️ 不用 `tmp_path`（AGENTS.md：受限环境不可写）；`storage` 的三个目录已被
conftest 指到临时目录。
"""

from __future__ import annotations

import csv
import io
import json
import uuid
import zipfile
from datetime import timedelta

from fastapi.testclient import TestClient
from helpers import TEST_USER_ID, create_user_row

import app.storage as storage
from app.db import SessionLocal
from app.main import app
from app.models import (
    AuthSession,
    BlockEdit,
    Draft,
    Material,
    MemoryEvent,
    Task,
    TaskBlock,
    User,
)
from app.timeutil import utc_now


def _other_user() -> int:
    """第二个账号（用来验证"看不见别人的东西"）。"""
    return create_user_row("me-other", "pw-12345678")


def _make_task(*, user_id: int = TEST_USER_ID, filename: str = "chem_arXiv.pdf") -> int:
    with SessionLocal() as session:
        row = Task(user_id=user_id, filename=filename, status="completed")
        session.add(row)
        session.commit()
        return row.id


def _make_material(*, user_id: int = TEST_USER_ID, task_id: int | None) -> int:
    with SessionLocal() as session:
        row = Material(
            user_id=user_id,
            task_id=task_id,
            block_id="p0_b1",
            text_quote="the chiral measures are conserved",
            translated_quote="手性测度是守恒的",
            page=1,
            source_name="chem_arXiv.pdf",
            created_at=utc_now(),
        )
        session.add(row)
        session.commit()
        return row.id


def _make_event(
    *,
    user_id: int = TEST_USER_ID,
    summary: str = "正文发往模型 API 翻译",
    payload: dict | None = None,
) -> int:
    with SessionLocal() as session:
        row = MemoryEvent(
            user_id=user_id,
            task_id=None,
            layer="L0",
            stage="translate",
            actor="api",
            tool="engine",
            summary=summary,
            payload=payload,
            created_at=utc_now(),
        )
        session.add(row)
        session.commit()
        return row.id


def _make_session(
    *, user_id: int = TEST_USER_ID, days: int = 30, agent: str = "Chrome / Windows"
) -> int:
    with SessionLocal() as session:
        now = utc_now()
        row = AuthSession(
            token_hash=uuid.uuid4().hex,
            user_id=user_id,
            created_at=now,
            expires_at=now + timedelta(days=days),
            last_seen_at=now,
            user_agent=agent,
        )
        session.add(row)
        session.commit()
        return row.id


# ============================================================ N24


def test_storage_measures_real_bytes_and_has_exact_keys() -> None:
    """磁盘占用是**真量**的：往 uploads 写一个文件，数字必须跟着涨。"""
    with TestClient(app) as client:
        before = client.get("/api/me/storage").json()
        payload = b"x" * 4096
        (storage.UPLOADS_DIR / "sample.pdf").write_bytes(payload)
        after = client.get("/api/me/storage").json()

    assert set(after) == {"total_bytes", "by_kind", "location"}
    assert set(after["by_kind"]) == {"uploads", "outputs", "backups", "db"}
    assert after["total_bytes"] == sum(after["by_kind"].values())
    assert after["location"]
    grown = after["by_kind"]["uploads"] - before["by_kind"]["uploads"]
    assert grown == len(payload)  # 差多少就是写进去多少，不是估的


# ============================================================ N26


def test_ledger_json_newest_first_and_shape() -> None:
    _make_event(summary="第一条（较早）")
    second = _make_event(summary="第二条（含引号与逗号,）", payload={"blocks": 42})

    with TestClient(app) as client:
        body = client.get("/api/me/ledger").json()

    assert set(body) == {"items"}
    assert [row["id"] for row in body["items"]][0] == second
    row = body["items"][0]
    assert set(row) == {
        "id",
        "task_id",
        "layer",
        "stage",
        "actor",
        "tool",
        "summary",
        "payload",
        "created_at",
    }
    assert row["payload"] == {"blocks": 42}
    assert row["created_at"].endswith("+00:00")


def test_ledger_csv_round_trips_through_a_real_parser() -> None:
    """RFC4180：**用标准解析器读回来必须与原值一模一样**（这才是"真能打开"）。"""
    messy = '含"引号"、逗号, 与\n换行'
    _make_event(summary=messy)

    with TestClient(app) as client:
        resp = client.get("/api/me/ledger", params={"format": "csv"})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "docwise-ledger.csv" in resp.headers["content-disposition"]
    assert resp.text.split("\n")[0] == "created_at,layer,stage,actor,tool,summary"

    rows = list(csv.reader(io.StringIO(resp.text)))
    assert rows[0] == ["created_at", "layer", "stage", "actor", "tool", "summary"]
    assert rows[1][5] == messy
    assert rows[1][1:5] == ["L0", "translate", "api", "engine"]


def test_ledger_markdown_escapes_pipe() -> None:
    _make_event(summary="左 | 右")

    with TestClient(app) as client:
        resp = client.get("/api/me/ledger", params={"format": "md"})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    head = "| 时间 | 环节 | 数据流向 | 说明 |\n|---|---|---|---|"
    assert resp.text.startswith(head)
    assert "左 \\| 右" in resp.text  # 竖线被转义，表格不会被切断


def test_ledger_hides_other_accounts_events() -> None:
    other = _other_user()
    mine = _make_event(summary="我的")
    _make_event(user_id=other, summary="别人的")

    with TestClient(app) as client:
        body = client.get("/api/me/ledger").json()

    assert [row["id"] for row in body["items"]] == [mine]


def test_ledger_rejects_unknown_format() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/me/ledger", params={"format": "xlsx"})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "format 只支持 json / csv / md"


# ============================================================ N25


def test_export_markdown_reports_real_counts() -> None:
    task_id = _make_task()
    _make_material(task_id=task_id)
    with SessionLocal() as session:
        session.add(Draft(user_id=TEST_USER_ID, title="开题报告", body_md=""))
        session.commit()

    with TestClient(app) as client:
        resp = client.get("/api/me/export", params={"format": "md"})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "文献：1 篇" in resp.text
    assert "素材卡：1 条" in resp.text
    assert "草稿：1 篇" in resp.text


def test_export_zip_is_a_readable_archive() -> None:
    _make_task(filename="我的文献.pdf")
    _make_event(summary="取字（本地）")

    with TestClient(app) as client:
        resp = client.get("/api/me/export")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/zip")
    assert "docwise-export.zip" in resp.headers["content-disposition"]

    with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
        names = set(archive.namelist())
        assert {"data.json", "ledger.csv", "README.md"} <= names
        payload = json.loads(archive.read("data.json").decode("utf-8"))
        readme = archive.read("README.md").decode("utf-8")
        ledger = archive.read("ledger.csv").decode("utf-8")

    assert [task["filename"] for task in payload["tasks"]] == ["我的文献.pdf"]
    assert payload["memory_events"][0]["summary"] == "取字（本地）"
    assert payload["account"]["username"] == "tester"
    assert "uploads" in readme  # 说清原始 PDF 不在包里
    assert ledger.startswith("created_at,layer,stage,actor,tool,summary")


def test_export_rejects_unknown_format() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/me/export", params={"format": "tar"})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "format 只支持 zip / md"


# ============================================================ N29


def test_sessions_list_only_mine_and_only_unexpired() -> None:
    other = _other_user()
    fresh = _make_session(agent="Chrome / Windows")
    _make_session(days=-1, agent="已经过期的")  # 过期的不摆出来凑数
    _make_session(user_id=other, agent="别人的")

    with TestClient(app) as client:
        body = client.get("/api/me/sessions").json()

    assert set(body) == {"items"}
    assert [row["id"] for row in body["items"]] == [fresh]
    row = body["items"][0]
    assert set(row) == {"id", "created_at", "expires_at", "last_seen_at", "user_agent"}
    assert row["user_agent"] == "Chrome / Windows"
    assert row["expires_at"].endswith("+00:00")
    assert row["last_seen_at"].endswith("+00:00")


def test_revoke_session_only_mine() -> None:
    other = _other_user()
    mine = _make_session(agent="Chrome / Windows")
    theirs = _make_session(user_id=other, agent="别人的")

    with TestClient(app) as client:
        ok = client.delete(f"/api/me/sessions/{mine}")
        denied = client.delete(f"/api/me/sessions/{theirs}")
        missing = client.delete("/api/me/sessions/99999")

    assert ok.status_code == 200
    assert ok.json() == {"deleted": True, "id": mine}
    assert denied.status_code == 404
    assert denied.json()["detail"] == "会话不存在"
    assert missing.status_code == 404
    with SessionLocal() as session:
        assert session.get(AuthSession, mine) is None  # 我的真删了
        assert session.get(AuthSession, theirs) is not None  # 别人的没动


# ============================================================ N28 / N30


def test_patch_me_validates_and_persists() -> None:
    with TestClient(app) as client:
        noop = client.patch("/api/me", json={})
        renamed = client.patch("/api/me", json={"display_name": "  新名字  "})

    assert noop.status_code == 200
    assert noop.json()["display_name"] == "测试用户"  # 空 body = 什么都不改

    assert renamed.status_code == 200
    assert renamed.json()["display_name"] == "新名字"  # 前后空格被去掉
    assert "last_login_at" in renamed.json()  # N30：只追加，不改现有字段
    with SessionLocal() as session:
        assert session.get(User, TEST_USER_ID).display_name == "新名字"


def test_patch_me_rejects_bad_display_name() -> None:
    with TestClient(app) as client:
        blank = client.patch("/api/me", json={"display_name": "   "})
        none = client.patch("/api/me", json={"display_name": None})
        toolong = client.patch("/api/me", json={"display_name": "字" * 65})

    for resp in (blank, none, toolong):
        assert resp.status_code == 400
        assert resp.json()["detail"] == "显示名要 1–64 个字"


def test_auth_me_carries_last_login_at_even_when_never_logged_in() -> None:
    """N30：字段**永远在**（没有就是 null）——前端据此写"暂未记录"，不许编时间。"""
    with TestClient(app) as client:
        body = client.get("/api/auth/me").json()

    assert "last_login_at" in body
    assert body["last_login_at"] is None


# ============================================================ N27


def test_delete_me_purges_my_data_and_keeps_others() -> None:
    other = _other_user()

    task_id = _make_task(filename="我的文献.pdf")
    with SessionLocal() as session:
        session.add(TaskBlock(task_id=task_id, block_id="p0_b1", text="hello"))
        session.add(
            BlockEdit(
                user_id=TEST_USER_ID,
                task_id=task_id,
                block_id="p0_b1",
                text_hash="hash",
                before="模型译文",
                after="我改过的译文",
            )
        )
        session.commit()
    _make_material(task_id=task_id)
    _make_event(summary="我的台账")
    _make_session(agent="Chrome / Windows")

    other_task = _make_task(user_id=other, filename="别人的文献.pdf")
    other_material = _make_material(user_id=other, task_id=other_task)
    other_event = _make_event(user_id=other, summary="别人的台账")

    # 我的上传原件真的落在盘上（删账号时要一并清掉）
    mine_file = storage.UPLOADS_DIR / "mine.pdf"
    mine_file.write_bytes(b"%PDF-1.4 mine")
    with SessionLocal() as session:
        session.get(Task, task_id).original_path = str(mine_file)
        session.commit()

    with TestClient(app) as client:
        resp = client.delete("/api/me")

    assert resp.status_code == 200
    assert resp.json() == {"deleted": True, "id": TEST_USER_ID}

    with SessionLocal() as session:
        assert session.get(User, TEST_USER_ID) is None
        assert session.query(Task).filter_by(user_id=TEST_USER_ID).count() == 0
        assert session.query(Material).filter_by(user_id=TEST_USER_ID).count() == 0
        assert session.query(MemoryEvent).filter_by(user_id=TEST_USER_ID).count() == 0
        assert session.query(AuthSession).filter_by(user_id=TEST_USER_ID).count() == 0
        assert session.query(Draft).filter_by(user_id=TEST_USER_ID).count() == 0
        assert session.query(BlockEdit).filter_by(user_id=TEST_USER_ID).count() == 0
        # ⭐ 别人的数据一动不动
        assert session.get(Task, other_task) is not None
        assert session.get(Material, other_material) is not None
        assert session.get(MemoryEvent, other_event) is not None

    assert not mine_file.exists()  # 磁盘产物按任务清掉了
