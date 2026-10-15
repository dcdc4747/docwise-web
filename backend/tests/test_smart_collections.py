"""知识库 · 智能集合（契约 §2.3 / N9–N11）的测试。

盯五件事：

1. ⭐ **内置三条自愈**：迁移只覆盖"当时已存在"的账号，所以读接口要能补上
   （缺哪条补哪条，齐了一次库都不写——反复读不许长出重复行）；
2. ⭐ **规则真的在算**：`count` 由规则当场算出，**归档的不算**；
3. ⭐ **两条路必须一致**：`N9` 的 `count` 与 `GET /api/tasks?smart_id=`
   的结果条数不能打架
   （它们共用 `routers/tasks.py` 的同一套匹配，这正是"不写第二套逻辑"的判据）；
4. **query 非法 → 400**（空 `all` / 未知 field / 未知 op / 缺 value 四种都挡）；
5. **内置不许删（400）**、别人的规则 404。

⚠️ 不用 `tmp_path`（AGENTS.md：受限环境不可写）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import TEST_USER_ID, create_user_row

from app.db import SessionLocal
from app.main import app
from app.models import SmartCollection, Task
from app.smart_rules import BUILTIN_NAMES
from app.timeutil import utc_now

client = TestClient(app)


def _task(*, reading_status: str = "todo", archived: bool = False) -> int:
    with SessionLocal() as session:
        row = Task(
            user_id=TEST_USER_ID,
            filename="p.pdf",
            status="completed",
            reading_status=reading_status,
        )
        if archived:
            row.archived_at = utc_now()
        session.add(row)
        session.commit()
        return row.id


def _rule(value: str = "todo") -> dict:
    """`状态 = <value>` 这条规则（用例里反复用，别各写一份字面量）。"""
    return {"all": [{"field": "reading_status", "op": "eq", "value": value}]}


def _items() -> list[dict]:
    response = client.get("/api/smart-collections")
    assert response.status_code == 200
    return response.json()["items"]


def test_list_seeds_builtins_once_and_is_idempotent():
    """⭐ 新账号第一次读就有三条内置规则；反复读不长重复行。"""
    with SessionLocal() as session:
        assert session.query(SmartCollection).count() == 0  # 迁移没覆盖这个测试账号

    first = _items()
    assert [row["name"] for row in first] == list(BUILTIN_NAMES)
    assert all(row["builtin"] is True for row in first)

    again = _items()
    assert [row["id"] for row in again] == [row["id"] for row in first]
    with SessionLocal() as session:
        assert session.query(SmartCollection).count() == len(BUILTIN_NAMES)


def test_counts_follow_the_rules_and_skip_archived():
    _task(reading_status="todo")
    _task(reading_status="reading")
    _task(reading_status="reading")
    _task(reading_status="done")
    _task(reading_status="done", archived=True)  # 归档的不算

    counts = {row["name"]: row["count"] for row in _items()}
    assert counts == {"待读": 1, "在读": 2, "已读": 1}


def test_n9_count_agrees_with_the_task_list_filter():
    """⭐ 同一个规则，列表里的 `count` 与 `?smart_id=` 的结果必须一样。"""
    _task(reading_status="todo")
    _task(reading_status="todo")
    _task(reading_status="done")
    todo = next(row for row in _items() if row["name"] == "待读")

    response = client.get(f"/api/tasks?smart_id={todo['id']}")
    assert response.status_code == 200
    assert len(response.json()) == todo["count"] == 2


def test_post_validates_query_shape():
    for bad in (
        {"name": "空规则", "query": {"all": []}},
        {"name": "不是对象", "query": "todo"},
        {
            "name": "未知字段",
            "query": {"all": [{"field": "nope", "op": "eq", "value": 1}]},
        },
        {
            "name": "未知算子",
            "query": {"all": [{"field": "reading_status", "op": "like", "value": "x"}]},
        },
        {
            "name": "缺 value",
            "query": {"all": [{"field": "reading_status", "op": "eq"}]},
        },
    ):
        response = client.post("/api/smart-collections", json=bad)
        assert response.status_code == 400, bad

    empty_name = {"name": "", "query": _rule()}
    assert client.post("/api/smart-collections", json=empty_name).status_code == 400


def test_post_creates_custom_rule_with_count():
    _task(reading_status="done")
    query = _rule("done")
    response = client.post(
        "/api/smart-collections", json={"name": "只看已读", "query": query}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["builtin"] is False
    assert body["count"] == 1
    assert body["query"] == query


def test_delete_builtin_is_400_and_custom_is_ok():
    builtin_id = _items()[0]["id"]
    response = client.delete(f"/api/smart-collections/{builtin_id}")
    assert response.status_code == 400
    assert "内置" in response.json()["detail"]

    custom = client.post(
        "/api/smart-collections", json={"name": "临时", "query": _rule()}
    ).json()
    assert client.delete(f"/api/smart-collections/{custom['id']}").status_code == 200
    assert custom["id"] not in [row["id"] for row in _items()]
    assert client.delete("/api/smart-collections/9999").status_code == 404


def test_others_rule_is_404():
    other = create_user_row("other-smart", "pw-other")
    with SessionLocal() as session:
        row = SmartCollection(
            user_id=other,
            name="别人的规则",
            query=_rule(),
            builtin=False,
        )
        session.add(row)
        session.commit()
        theirs = row.id

    assert client.get("/api/smart-collections").json()["items"] == [] or all(
        row["id"] != theirs for row in _items()
    )
    assert client.delete(f"/api/smart-collections/{theirs}").status_code == 404
