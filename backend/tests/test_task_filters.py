"""N8：`GET /api/tasks` 上的四个筛选参数（契约 §2.2）。

为什么值得一组独立用例：**筛选条已经合进前端了**（`LibFilters.vue`，卡③）。
如果后端这条链路只是"接了参数但筛不出不同结果"，界面上就是
"看起来能用其实没用"——比没有这个功能更糟。
所以这里每条都断言**筛出来的 id 集合**，不是"返回了东西"。

口径与前端 mock **逐字一致**（那条 mock 是前端的离线契约）：

- 多条参数之间 **AND**；
- `collection_id` 按**直接成员**算（子集合不算，与集合计数同一语义）；
- `tag[]` 与 `?tag=` 两种写法都收，**每个标签都要命中**；
- `smart_id` 套那条规则的 `query`；**查不到的 id → 空数组**；
- **不传参数** → 与老行为一致（全部、新的在前、最多 50 条、归档的不出）。

⚠️ 这几个参数**不是新端点**，是给基线端点**追加查询参数**（契约 §3 末的口径），
所以 `backend/.contract/api.json` 的端点清单**不变**。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import TEST_USER_ID

from app.db import SessionLocal
from app.main import app
from app.models import Collection, SmartCollection, Tag, Task, TaskCollection, TaskTag
from app.timeutil import utc_now


def _make_task(filename: str, **kwargs) -> int:
    """直接入库建任务（带归属，不走上传、不触发 worker）。"""
    with SessionLocal() as session:
        task = Task(
            user_id=kwargs.pop("user_id", TEST_USER_ID),
            filename=filename,
            tier="fast",
            status="completed",
            progress=1.0,
            source_lang=kwargs.pop("source_lang", "en"),
            target_lang=kwargs.pop("target_lang", "zh"),
            **kwargs,
        )
        session.add(task)
        session.commit()
        return task.id


def _make_collection(name: str, parent_id: int | None = None) -> int:
    with SessionLocal() as session:
        row = Collection(user_id=TEST_USER_ID, name=name, parent_id=parent_id)
        session.add(row)
        session.commit()
        return row.id


def _make_tag(name: str, kind: str = "topic") -> int:
    with SessionLocal() as session:
        row = Tag(user_id=TEST_USER_ID, name=name, kind=kind)
        session.add(row)
        session.commit()
        return row.id


def _link_collection(task_id: int, collection_id: int) -> None:
    with SessionLocal() as session:
        session.add(TaskCollection(task_id=task_id, collection_id=collection_id))
        session.commit()


def _link_tag(task_id: int, tag_id: int) -> None:
    with SessionLocal() as session:
        session.add(TaskTag(task_id=task_id, tag_id=tag_id))
        session.commit()


def _make_smart(name: str, query: dict) -> int:
    with SessionLocal() as session:
        row = SmartCollection(
            user_id=TEST_USER_ID, name=name, query=query, builtin=False
        )
        session.add(row)
        session.commit()
        return row.id


def _ids(client: TestClient, query: str = "") -> list[int]:
    resp = client.get(f"/api/tasks{query}")
    assert resp.status_code == 200, resp.text
    return [item["id"] for item in resp.json()]


def _three_tasks() -> tuple[int, int, int]:
    """三篇：待读 / 在读 / 已读（`reading_status` 不传就是默认的 `todo`）。"""
    todo = _make_task("todo.pdf", reading_status="todo")
    reading = _make_task("reading.pdf", reading_status="reading")
    done = _make_task("done.pdf", reading_status="done")
    return todo, reading, done


def test_no_params_keeps_baseline_behaviour() -> None:
    """不传参数 = 老行为：全部返回、新的在前、最多 50 条。"""
    todo, reading, done = _three_tasks()
    with TestClient(app) as client:
        ids = _ids(client)
    assert ids == [done, reading, todo]  # id 倒序 = 新的在前


def test_reading_status_filters_to_different_sets() -> None:
    """⭐ 判据：同一个参数传不同值 → **不同结果**（不是永远返回同一份）。"""
    todo, reading, done = _three_tasks()
    with TestClient(app) as client:
        assert _ids(client, "?reading_status=todo") == [todo]
        assert _ids(client, "?reading_status=reading") == [reading]
        assert _ids(client, "?reading_status=done") == [done]
        assert _ids(client, "?reading_status=archived") == []


def test_collection_filter_counts_direct_members_only() -> None:
    """`collection_id` 按**直接成员**算：挂进子集合的文献不算在父集合里。"""
    parent = _make_collection("父集合")
    child = _make_collection("子集合", parent_id=parent)
    outer = _make_task("outer.pdf")
    inner = _make_task("inner.pdf")
    _link_collection(outer, parent)
    _link_collection(inner, child)

    with TestClient(app) as client:
        assert _ids(client, f"?collection_id={parent}") == [outer]
        assert _ids(client, f"?collection_id={child}") == [inner]


def test_tag_filter_accepts_both_spellings_and_requires_all() -> None:
    """`?tag[]=A&tag[]=B` 与 `?tag=A` 都收；**多个标签是 AND**。"""
    rag = _make_tag("RAG")
    survey = _make_tag("综述")
    both = _make_task("both.pdf")
    only_rag = _make_task("only-rag.pdf")
    _link_tag(both, rag)
    _link_tag(both, survey)
    _link_tag(only_rag, rag)

    with TestClient(app) as client:
        by_bracket = _ids(client, "?tag[]=RAG")
        assert sorted(by_bracket) == sorted([both, only_rag])
        assert _ids(client, "?tag[]=RAG&tag[]=综述") == [both]
        assert _ids(client, "?tag=RAG") == by_bracket
        assert _ids(client, "?tag[]=不存在的标签") == []


def test_smart_id_applies_the_rule() -> None:
    """⭐ 规则即数据：`smart_id` 真的按那条 `query` 筛（三种 op 各验一遍）。"""
    # ⚠️ `reading_status` 不传就是默认的 `todo`，所以这里每篇都显式给值
    todo = _make_task("todo.pdf", reading_status="todo")
    reading = _make_task("reading.pdf", reading_status="reading")
    chinese = _make_task(
        "cn.pdf", source_lang="zh", target_lang="zh", reading_status="done"
    )
    scanned = _make_task("scan.pdf", text_source="ocr", reading_status="done")

    eq_todo = _make_smart(
        "待读", {"all": [{"field": "reading_status", "op": "eq", "value": "todo"}]}
    )
    unread = _make_smart(
        "没读完的",
        {
            "all": [
                {"field": "reading_status", "op": "in", "value": ["todo", "reading"]}
            ]
        },
    )
    not_ocr = _make_smart(
        "非扫描件",
        {"all": [{"field": "text_source", "op": "not_in", "value": ["ocr"]}]},
    )
    is_native = _make_smart(
        "中文文献", {"all": [{"field": "native", "op": "eq", "value": True}]}
    )

    with TestClient(app) as client:
        assert _ids(client, f"?smart_id={eq_todo}") == [todo]
        assert sorted(_ids(client, f"?smart_id={unread}")) == sorted([todo, reading])
        assert scanned not in _ids(client, f"?smart_id={not_ocr}")
        assert _ids(client, f"?smart_id={is_native}") == [chinese]


def test_smart_rule_with_tag_and_collection_fields() -> None:
    """规则里也能用 `tag` / `collection`（它们是**列表**：`eq` 按成员算）。"""
    collection = _make_collection("手性课题")
    tag_id = _make_tag("酶催化")
    hit = _make_task("hit.pdf")
    _link_collection(hit, collection)
    _link_tag(hit, tag_id)
    _make_task("miss.pdf")

    by_tag = _make_smart(
        "酶催化", {"all": [{"field": "tag", "op": "eq", "value": "酶催化"}]}
    )
    by_collection = _make_smart(
        "手性课题", {"all": [{"field": "collection", "op": "eq", "value": collection}]}
    )

    with TestClient(app) as client:
        assert _ids(client, f"?smart_id={by_tag}") == [hit]
        assert _ids(client, f"?smart_id={by_collection}") == [hit]


def test_unknown_smart_id_returns_empty_not_error() -> None:
    """查不到的 `smart_id` → **空数组**（契约没为它定义错误）。"""
    _three_tasks()
    with TestClient(app) as client:
        resp = client.get("/api/tasks?smart_id=999999")
        assert resp.status_code == 200
        assert resp.json() == []


def test_multiple_params_are_combined_with_and() -> None:
    """多条参数是交集，不是并集。"""
    todo = _make_task("todo.pdf", reading_status="todo")
    reading = _make_task("reading.pdf", reading_status="reading")
    collection = _make_collection("手性课题")
    _link_collection(todo, collection)
    _link_collection(reading, collection)

    with TestClient(app) as client:
        hit = _ids(client, f"?reading_status=todo&collection_id={collection}")
        assert hit == [todo]
        assert _ids(client, f"?reading_status=done&collection_id={collection}") == []


def test_archived_tasks_stay_hidden_under_every_filter() -> None:
    """归档的文献在**任何筛选下都不出现**（藏 ≠ 删，筛选不该把它翻出来）。"""
    visible = _make_task("visible.pdf", reading_status="todo")
    _make_task("archived.pdf", reading_status="todo", archived_at=utc_now())

    with TestClient(app) as client:
        assert _ids(client, "?reading_status=todo") == [visible]


def test_only_the_current_user_tasks_are_listed() -> None:
    """别人的任务不出现在自己的筛选结果里（归属过滤在筛选之前就生效）。"""
    mine = _make_task("mine.pdf", reading_status="todo")
    _make_task("theirs.pdf", reading_status="todo", user_id=2)

    with TestClient(app) as client:
        assert _ids(client, "?reading_status=todo") == [mine]


def test_filtered_response_has_the_same_shape() -> None:
    """筛过的响应与不筛**形状一致**（同一个序列化器，别筛出另一套字段）。"""
    _three_tasks()
    with TestClient(app) as client:
        plain = client.get("/api/tasks").json()
        filtered = client.get("/api/tasks?reading_status=todo").json()
    assert filtered and set(filtered[0]) == set(plain[0])


def test_match_condition_ops_are_frozen() -> None:
    """纯函数那三条 op 的判定（列表按成员、未知 op 一律不匹配）。"""
    from app.routers.tasks import _match_condition

    assert _match_condition(["a", "b"], "eq", "a") is True
    assert _match_condition(["a", "b"], "eq", "c") is False
    assert _match_condition("todo", "eq", "todo") is True
    assert _match_condition("todo", "in", ["todo", "reading"]) is True
    assert _match_condition("done", "in", ["todo", "reading"]) is False
    assert _match_condition("done", "not_in", ["todo", "reading"]) is True
    assert _match_condition(None, "eq", "todo") is False  # 没值不匹配
    assert _match_condition("todo", "gt", "todo") is False  # 未知 op：不匹配


def test_rule_value_reads_the_same_fields_as_the_api() -> None:
    """`native` 必须与接口输出的 `native` **同一条口径**（`is_native_pair`）。"""
    from app.routers.tasks import _rule_value

    chinese_id = _make_task("cn.pdf", source_lang="zh", target_lang="zh")
    english_id = _make_task("en.pdf")
    with SessionLocal() as session:
        chinese = session.get(Task, chinese_id)
        english = session.get(Task, english_id)
    context: dict[str, dict[int, list]] = {"tag": {}, "collection": {}}
    assert _rule_value(chinese, "native", context) is True
    assert _rule_value(english, "native", context) is False
    assert _rule_value(chinese, "不认识的字段", context) is None
