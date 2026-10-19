"""文献对比工具包（`app/agent/packs/compare.py`）的用例。

盯四件事：

1. 两篇都有导读与术语 → 共同术语、各自独有术语、导读逐字段并排；
2. 一篇没有导读 → 那一侧如实写 `None` + `guide_missing`，不拿另一侧去填；
3. 别人的 task → 返回一句人话，不抛异常、不泄露文件名；
4. 同一篇自己比自己 → 不崩，`same_terms` 覆盖全部术语。

⚠️ 不用 `tmp_path`、不用 db_session（AGENTS.md：受限环境不可写）；
数据自己用 `SessionLocal` 建、自己清。
"""

from __future__ import annotations

import json

from helpers import TEST_USER_ID

from app.agent.contracts import ToolContext
from app.agent.packs import compare as compare_pack
from app.db import SessionLocal
from app.models import Task, TaskUnderstanding


def _ctx() -> ToolContext:
    return ToolContext(
        db=None,
        user_id=TEST_USER_ID,
        scene_id="read_ask",
        scope={},
    )


def _make_task(
    *, user_id: int = TEST_USER_ID, filename: str = "paper.pdf"
) -> int:
    with SessionLocal() as session:
        row = Task(user_id=user_id, filename=filename, status="completed")
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def _make_understanding(
    task_id: int,
    *,
    guide: dict | None = None,
    terms: list[dict] | None = None,
    guide_raw: str | None = None,
    terms_raw: str | None = None,
    status: str = "ready",
) -> None:
    if guide is not None:
        guide_raw = json.dumps(guide, ensure_ascii=False)
    if terms is not None:
        terms_raw = json.dumps(terms, ensure_ascii=False)
    with SessionLocal() as session:
        session.add(
            TaskUnderstanding(
                task_id=task_id,
                guide_json=guide_raw,
                terms_json=terms_raw,
                status=status,
            )
        )
        session.commit()


def _guide(**fields: str) -> dict:
    """导读的真实结构：`{字段: {"text": …, "source_block_ids": […]}}`。"""
    return {
        key: {"text": text, "source_block_ids": ["p0_b1"]}
        for key, text in fields.items()
    }


def _drop(*task_ids: int) -> None:
    with SessionLocal() as session:
        for task_id in task_ids:
            session.query(TaskUnderstanding).filter_by(task_id=task_id).delete()
            task = session.get(Task, task_id)
            if task is not None:
                session.delete(task)
        session.commit()


# ============================================================ ① 两边都齐
def test_compare_reports_shared_and_unique_terms() -> None:
    a_id = _make_task(filename="chem.pdf")
    b_id = _make_task(filename="math.pdf")
    _make_understanding(
        a_id,
        guide=_guide(
            research_question="手性时间结构能否分开？",
            method="数值模拟",
            conclusion="手性可以分成时间与空间两部分。",
        ),
        terms=[
            {"term": "chirality", "cn": "手性", "definition": "左右手性"},
            {"term": "time crystal", "cn": "时间晶体", "definition": "周期性"},
        ],
    )
    _make_understanding(
        b_id,
        guide=_guide(
            research_question="手性时间结构能否分开？",
            method="数值模拟",
            conclusion="手性只是一个近似。",
        ),
        terms=[
            {"term": "Chirality", "cn": "手性", "definition": "左右手性"},
            {"term": "decoherence", "cn": "退相干", "definition": "环境耦合"},
        ],
    )

    result = compare_pack.compare_documents(
        _ctx(), {"task_a": a_id, "task_b": b_id}
    )
    data = result.data
    assert isinstance(data, dict)
    assert data["a"]["task_id"] == a_id
    assert data["a"]["filename"] == "chem.pdf"
    assert data["a"]["guide_keys"] == [
        "research_question",
        "method",
        "conclusion",
    ]
    assert data["a"]["guide_missing"] is False
    assert data["a"]["terms_missing"] is False
    assert data["b"]["guide_missing"] is False

    assert {item["term"].casefold() for item in data["same_terms"]} == {
        "chirality"
    }
    assert data["same_terms"][0]["cn_matches"] is True
    assert [item["term"] for item in data["only_a_terms"]] == ["time crystal"]
    assert [item["term"] for item in data["only_b_terms"]] == ["decoherence"]

    diff = data["guide_diff"]
    assert diff["research_question"]["same"] is True
    assert diff["method"]["same"] is True
    assert diff["conclusion"]["same"] is False
    assert diff["conclusion"]["a"].startswith("手性可以")
    assert diff["conclusion"]["b"].startswith("手性只是")
    assert "共同术语 1 条" in result.note

    _drop(a_id, b_id)


# ============================================================ ② 缺导读
def test_missing_guide_is_flagged_not_fabricated() -> None:
    a_id = _make_task(filename="a.pdf")
    b_id = _make_task(filename="b.pdf")
    _make_understanding(
        a_id,
        guide=_guide(conclusion="A 的结论。"),
        terms=[{"term": "chirality", "cn": "手性"}],
    )
    # B 有术语、但没有导读（界面还没点「导读」）
    _make_understanding(
        b_id, terms=[{"term": "chirality", "cn": "手性"}]
    )

    result = compare_pack.compare_documents(
        _ctx(), {"task_a": a_id, "task_b": b_id}
    )
    data = result.data
    assert data["b"]["guide_missing"] is True
    assert data["b"]["guide_keys"] == []

    diff = data["guide_diff"]
    assert diff["conclusion"]["a"] == "A 的结论。"
    assert diff["conclusion"]["b"] is None, "缺导读就写 None，不许编"
    assert diff["conclusion"]["same"] is False
    assert "第 2 篇没有导读" in result.note

    # 术语这边照常对比，不因为缺导读就整条失败
    assert len(data["same_terms"]) == 1
    assert data["only_a_terms"] == []
    assert data["only_b_terms"] == []

    _drop(a_id, b_id)


# ============================================================ ③ 别人的 task
def test_other_users_task_is_refused_in_plain_words() -> None:
    mine = _make_task(filename="mine.pdf")
    theirs = _make_task(user_id=TEST_USER_ID + 999, filename="theirs.pdf")
    _make_understanding(mine, guide=_guide(conclusion="我的结论。"))

    result = compare_pack.compare_documents(
        _ctx(), {"task_a": mine, "task_b": theirs}
    )
    assert isinstance(result.data, str), "读不到就回一句人话，不返回结构"
    assert "找不到第 2 篇" in result.data
    assert "theirs.pdf" not in result.data, "别人的文件名也不该泄露"

    missing = compare_pack.compare_documents(
        _ctx(), {"task_a": 99_999_999, "task_b": mine}
    )
    assert isinstance(missing.data, str)
    assert "找不到第 1 篇" in missing.data

    _drop(mine, theirs)


# ============================================================ ④ 自己比自己
def test_self_compare_keeps_every_term() -> None:
    task_id = _make_task(filename="self.pdf")
    terms = [
        {"term": "chirality", "cn": "手性"},
        {"term": "time crystal", "cn": "时间晶体"},
        {"term": "decoherence", "cn": "退相干"},
    ]
    _make_understanding(
        task_id,
        guide=_guide(
            research_question="同一个问题",
            conclusion="同一个结论",
        ),
        terms=terms,
    )

    result = compare_pack.compare_documents(
        _ctx(), {"task_a": task_id, "task_b": task_id}
    )
    data = result.data
    assert isinstance(data, dict)
    assert data["a"]["task_id"] == data["b"]["task_id"] == task_id
    assert {item["term"] for item in data["same_terms"]} == {
        "chirality",
        "time crystal",
        "decoherence",
    }
    assert all(item["cn_matches"] for item in data["same_terms"])
    assert data["only_a_terms"] == []
    assert data["only_b_terms"] == []
    assert all(field["same"] for field in data["guide_diff"].values())

    _drop(task_id)


# ============================================================ ⑤ args / 坏 JSON
def test_args_and_broken_json_never_raise() -> None:
    # 没给参数
    no_args = compare_pack.compare_documents(_ctx(), None)
    assert isinstance(no_args.data, str)
    assert "task_a" in no_args.data
    assert isinstance(
        compare_pack.compare_documents(_ctx(), {"task_a": "abc"}).data, str
    )

    task_id = _make_task(filename="broken.pdf")
    _make_understanding(task_id, guide_raw="{不是 JSON", terms_raw="也坏了")

    # 字符串数字也认；坏 JSON 当缺失，不炸
    result = compare_pack.compare_documents(
        _ctx(), {"task_a": str(task_id), "task_b": task_id}
    )
    data = result.data
    assert data["a"]["guide_missing"] is True
    assert data["a"]["terms_missing"] is True
    assert data["a"]["guide_keys"] == []
    assert data["guide_diff"] == {}
    assert "没有导读" in result.note

    _drop(task_id)
