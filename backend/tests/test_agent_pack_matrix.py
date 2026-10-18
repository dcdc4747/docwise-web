"""综述矩阵工具包（`app/agent/packs/matrix.py`）的用例。

盯四件事（外加 args 容错）：

1. 两篇有导读 → 两行，字段逐字来自导读，术语只取前 5 个，引用句只取**被引用的**素材；
2. 一篇没导读 → 进 `missing`，**不进 rows**（不假装有内容）；
3. `topic` 过滤生效（文件名 / 导读文本、大小写不敏感），没匹配时如实说；
4. 别人的文献不出现（归属只看 `ctx.user_id`）。

⚠️ 不用 `tmp_path`、不用 db_session（AGENTS.md：受限环境不可写）；
数据自己用 `SessionLocal` 建、自己清。
"""

from __future__ import annotations

import json

from helpers import TEST_USER_ID

from app.agent.contracts import ToolContext
from app.agent.packs import matrix as matrix_pack
from app.db import SessionLocal
from app.models import Citation, Draft, Material, Task, TaskUnderstanding

_COLUMNS = ["文献", "研究问题", "方法", "结论", "术语", "可引用句"]


def _ctx() -> ToolContext:
    return ToolContext(
        db=None,
        user_id=TEST_USER_ID,
        scene_id="write_compose",
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


def _add_material(
    task_id: int, quote: str, *, user_id: int = TEST_USER_ID
) -> int:
    """建一份素材卡并**插一条引文**（=`被引用的素材`）；返回素材 id。"""
    with SessionLocal() as session:
        draft = Draft(
            user_id=user_id, title=f"matrix-draft-{task_id}", body_md=""
        )
        session.add(draft)
        session.flush()
        material = Material(
            user_id=user_id,
            task_id=task_id,
            block_id="p0_b1",
            text_quote=quote,
            page=1,
            source_name=f"{task_id}.pdf",
        )
        session.add(material)
        session.flush()
        session.add(
            Citation(
                draft_id=draft.id,
                material_id=material.id,
                order=1,
                csl_json={"title": "t"},
                anchor={"offset": 0},
            )
        )
        session.commit()
        return material.id


def _add_uncited_material(
    task_id: int, quote: str, *, user_id: int = TEST_USER_ID
) -> int:
    """只建素材卡、不插引文（不该被矩阵当成"可引用句"）。"""
    with SessionLocal() as session:
        material = Material(
            user_id=user_id,
            task_id=task_id,
            block_id="p0_b2",
            text_quote=quote,
            page=1,
            source_name=f"{task_id}.pdf",
        )
        session.add(material)
        session.commit()
        session.refresh(material)
        return material.id


def _drop(*task_ids: int) -> None:
    with SessionLocal() as session:
        materials = (
            session.query(Material)
            .filter(Material.task_id.in_(task_ids))
            .all()
        )
        material_ids = [material.id for material in materials]
        draft_ids: list[int] = []
        if material_ids:
            citations = (
                session.query(Citation)
                .filter(Citation.material_id.in_(material_ids))
                .all()
            )
            draft_ids = [citation.draft_id for citation in citations]
            for citation in citations:
                session.delete(citation)
            for material in materials:
                session.delete(material)
        for draft_id in set(draft_ids):
            draft = session.get(Draft, draft_id)
            if draft is not None:
                session.delete(draft)
        session.query(TaskUnderstanding).filter(
            TaskUnderstanding.task_id.in_(task_ids)
        ).delete(synchronize_session=False)
        for task_id in task_ids:
            task = session.get(Task, task_id)
            if task is not None:
                session.delete(task)
        session.commit()


# ============================================================ ① 两篇都有导读
def test_two_guided_documents_become_two_rows() -> None:
    a_id = _make_task(filename="手性-化学.pdf")
    b_id = _make_task(filename="手性-数学.pdf")
    _make_understanding(
        a_id,
        guide=_guide(
            research_question="手性时间结构能否分开？",
            method="数值模拟",
            conclusion="手性可以分成时间与空间两部分。",
        ),
        terms=[
            {"term": f"term{i}", "cn": f"术语{i}", "definition": "d"}
            for i in range(6)
        ],
    )
    _make_understanding(
        b_id,
        guide=_guide(
            research_question="手性只是一个近似吗？",
            method="解析推导",
            conclusion="手性只是一个近似。",
        ),
        terms=[{"term": "chirality", "cn": "手性", "definition": "左右手性"}],
    )
    _add_material(a_id, "手性可以分成时间与空间两部分。")
    _add_uncited_material(a_id, "这段素材没有被引用。")
    _add_material(b_id, "手性只是一个近似。")

    result = matrix_pack.build_matrix(_ctx(), {"topic": "手性"})
    data = result.data
    assert isinstance(data, dict)
    assert data["topic"] == "手性"
    assert data["columns"] == _COLUMNS
    assert data["missing"] == []
    assert len(data["rows"]) == 2

    by_id = {row["task_id"]: row for row in data["rows"]}
    assert set(by_id) == {a_id, b_id}

    row_a = by_id[a_id]
    assert row_a["file"] == "手性-化学.pdf"
    assert row_a["research_question"] == "手性时间结构能否分开？"
    assert row_a["method"] == "数值模拟"
    assert row_a["conclusion"] == "手性可以分成时间与空间两部分。"
    # 术语只取前 5 个（第 6 个 term5 不出现）
    assert row_a["terms"] == [f"term{i}" for i in range(5)]
    # 只认被引文引用过的素材，没引用的那条不算
    assert row_a["quote"] == "手性可以分成时间与空间两部分。"

    assert by_id[b_id]["terms"] == ["chirality"]
    assert by_id[b_id]["quote"] == "手性只是一个近似。"
    assert "2 篇" in result.note

    _drop(a_id, b_id)


# ============================================================ ② 缺导读
def test_guide_less_document_is_missing_not_a_row() -> None:
    guided_id = _make_task(filename="有导读-矩阵.pdf")
    missing_id = _make_task(filename="没导读-矩阵.pdf")
    _make_understanding(
        guided_id,
        guide=_guide(conclusion="有内容的结论。"),
        terms=[{"term": "matrix", "cn": "矩阵"}],
    )
    # 只有术语、没有导读：仍然算"还没有导读"，不许拿术语去填矩阵
    _make_understanding(
        missing_id, terms=[{"term": "matrix", "cn": "矩阵"}]
    )

    result = matrix_pack.build_matrix(_ctx(), {"topic": "矩阵"})
    data = result.data
    assert [row["task_id"] for row in data["rows"]] == [guided_id]
    assert data["missing"] == [{"task_id": missing_id, "why": "还没有导读"}]
    assert all(row["task_id"] != missing_id for row in data["rows"])
    assert "1 篇还没有导读" in result.note

    _drop(guided_id, missing_id)


# ============================================================ ③ topic 过滤
def test_topic_filter_matches_filename_and_guide_text() -> None:
    by_name = _make_task(filename="Chirality-A.pdf")
    by_guide = _make_task(filename="paper-2.pdf")
    other = _make_task(filename="topology.pdf")
    _make_understanding(
        by_name, guide=_guide(conclusion="手性可以分开。")
    )
    _make_understanding(
        by_guide, guide=_guide(conclusion="Chirality is a measure.")
    )
    _make_understanding(
        other, guide=_guide(conclusion="拓扑不变量。")
    )

    # 文件名（大小写不敏感）与导读文本都能命中；不相关的排除
    data = matrix_pack.build_matrix(
        _ctx(), {"topic": "chirality"}
    ).data
    assert {row["task_id"] for row in data["rows"]} == {by_name, by_guide}
    assert all(row["task_id"] != other for row in data["rows"])

    # 没有匹配 → rows 为空，并如实说
    empty = matrix_pack.build_matrix(_ctx(), {"topic": "量子"})
    assert empty.data["rows"] == []
    assert empty.data["missing"] == []
    assert empty.data["topic"] == "量子"
    assert "没有匹配的文献" in empty.note

    _drop(by_name, by_guide, other)


# ============================================================ ④ 别人的文献
def test_other_users_documents_never_appear() -> None:
    mine = _make_task(filename="Chirality-mine.pdf")
    theirs = _make_task(
        user_id=TEST_USER_ID + 999, filename="Chirality-theirs.pdf"
    )
    _make_understanding(mine, guide=_guide(conclusion="我的结论。"))
    _make_understanding(theirs, guide=_guide(conclusion="别人的结论。"))
    _add_material(mine, "我的可引用句。")
    _add_material(
        theirs, "别人的可引用句。", user_id=TEST_USER_ID + 999
    )

    result = matrix_pack.build_matrix(_ctx(), {"topic": "chirality"})
    data = result.data
    assert [row["task_id"] for row in data["rows"]] == [mine]
    assert data["missing"] == []
    assert all(row["task_id"] != theirs for row in data["rows"])
    assert "theirs" not in json.dumps(data, ensure_ascii=False)
    assert "别人的" not in json.dumps(data, ensure_ascii=False)

    _drop(mine, theirs)


# ============================================================ ⑤ args 容错 / 排序
def test_args_tolerance_and_guide_first_order() -> None:
    guided = _make_task(filename="older-guided.pdf")
    unguided = _make_task(filename="newer-no-guide.pdf")
    broken = _make_task(filename="broken.pdf")
    _make_understanding(guided, guide=_guide(conclusion="有导读。"))
    # 后建的两篇都没有导读（一篇完全没有理解层，一篇 JSON 读坏了）
    _make_understanding(broken, guide_raw="{不是 JSON", terms_raw="也坏了")

    # 不给参数不炸；默认 limit=10，有导读的排在前面
    no_args = matrix_pack.build_matrix(_ctx(), None)
    assert no_args.data["rows"][0]["task_id"] == guided
    assert {item["task_id"] for item in no_args.data["missing"]} == {
        unguided,
        broken,
    }

    # 字符串数字也认；topic 不是字符串就当没给
    limited = matrix_pack.build_matrix(_ctx(), {"limit": "1", "topic": 123})
    assert limited.data["topic"] == ""
    assert [row["task_id"] for row in limited.data["rows"]] == [guided]
    assert limited.data["missing"] == []
    # 有导读优先：即使 newer-no-guide 更晚建，limit=1 也先排 guided
    assert "还有 2 篇匹配但没显示" in limited.note

    _drop(guided, unguided, broken)
