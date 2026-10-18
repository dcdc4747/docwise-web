"""`check` 工具的术语一致率（`term_rate`）用例。

盯六件事：只用规范写法 = 100%；混用别名 < 100%，且人话里带
术语与百分比；术语表为空 / 正文为空 / 分母为 0 都回 `None`；
原有检查项一条不少；返回结构与 docstring 对得上。

⚠️ 不用 `tmp_path`：数据自己开 `SessionLocal` 建、跑完删。
"""

from __future__ import annotations

import json

import pytest
from helpers import TEST_USER_ID

from app.agent.contracts import ToolContext
from app.agent.packs import check as check_pack
from app.db import SessionLocal
from app.models import Citation, Draft, Material, Task, TaskUnderstanding

TERMS = [
    {"term": "chiral", "cn": "手性"},
    {"term": "enzyme", "cn": "酶"},
    {"term": "catalyst", "cn": "催化剂"},
    {"term": "solvent", "cn": "溶剂"},
]


def _ctx(draft_id: int) -> ToolContext:
    return ToolContext(
        db=None,
        user_id=TEST_USER_ID,
        scene_id="write_compose",
        scope={"draft_id": draft_id},
    )


def _make_draft(
    body: str, orders: tuple[int, ...] = (1,), terms=None
) -> tuple[int, int, int | None]:
    """建一篇本人的草稿；`terms` 给了就建来源文献与术语表。"""
    with SessionLocal() as session:
        task_id = None
        if terms is not None:
            task = Task(
                user_id=TEST_USER_ID,
                filename="术语来源.pdf",
                status="completed",
            )
            session.add(task)
            session.flush()
            task_id = task.id
            session.add(
                TaskUnderstanding(
                    task_id=task_id,
                    terms_json=json.dumps(terms, ensure_ascii=False),
                    status="ready",
                )
            )
        material = Material(
            user_id=TEST_USER_ID,
            task_id=task_id,
            text_quote="chiral measures are conserved",
            page=2,
            source_name="术语来源.pdf",
        )
        session.add(material)
        session.flush()
        draft = Draft(
            user_id=TEST_USER_ID, title="术语一致率用例", body_md=body
        )
        session.add(draft)
        session.flush()
        for order in orders:
            session.add(
                Citation(
                    draft_id=draft.id,
                    material_id=material.id,
                    order=order,
                    csl_json={
                        "type": "article-journal",
                        "title": f"文献{order}",
                        "author": [{"literal": "X"}],
                    },
                    anchor={"offset": 0},
                )
            )
        session.commit()
        return draft.id, material.id, task_id


def _drop(draft_id: int, material_id: int, task_id: int | None) -> None:
    """删掉用例造的数据（先删引文与子表，再删草稿、素材、文献）。"""
    with SessionLocal() as session:
        session.query(Citation).filter_by(draft_id=draft_id).delete()
        draft = session.get(Draft, draft_id)
        if draft is not None:
            session.delete(draft)
        material = session.get(Material, material_id)
        if material is not None:
            session.delete(material)
        if task_id is not None:
            session.query(TaskUnderstanding).filter_by(
                task_id=task_id
            ).delete()
            task = session.get(Task, task_id)
            if task is not None:
                session.delete(task)
        session.commit()


def test_canonical_only_reaches_full_rate() -> None:
    """正文只用规范写法 → 100%，分母写进 note。"""
    body = "手性中心很清楚，酶、催化剂、溶剂也都出现了。"
    ids = _make_draft(body, terms=TERMS)
    try:
        rate = check_pack.run_check(_ctx(ids[0])).data["term_rate"]
        assert rate["rate"] == 1.0
        assert (rate["total"], rate["ok"]) == (4, 4)
        assert "100%（4/4）" in rate["note"]
        assert "术语用法一致" in rate["note"]
    finally:
        _drop(*ids)


def test_alias_mixing_lowers_rate_and_names_term() -> None:
    """混用别名 → 低于 100%，人话里带术语、百分比与分母。"""
    # 同一术语来自两篇文献、两种译名：先到的当规范写法
    terms = TERMS + [{"term": "chiral", "cn": "手征"}]
    body = "这一段先说手性，后面又写手征；酶与催化剂也提到了。"
    ids = _make_draft(body, terms=terms)
    try:
        result = check_pack.run_check(_ctx(ids[0]))
        rate = result.data["term_rate"]
        # 溶剂没出现，不进分母：3 条里 chiral 混用，其余 2 条对
        assert rate["total"] == 3
        assert rate["ok"] == 2
        assert rate["rate"] == pytest.approx(2 / 3)
        assert rate["rate"] < 1
        assert "chiral" in rate["note"]
        assert "67%" in rate["note"]
        assert "2/3" in rate["note"]
        assert "手征" in rate["note"]
        # 原有那条"术语不一致"仍然在（判据没动）
        kinds = [item["kind"] for item in result.data["findings"]]
        assert "term_inconsistent" in kinds
    finally:
        _drop(*ids)


def test_empty_term_table_says_uncomputable() -> None:
    """术语表为空 → rate=None，note 说无法计算，不写 100%。"""
    ids = _make_draft("本文讨论手性中心。", terms=None)
    try:
        data = check_pack.run_check(_ctx(ids[0])).data
        rate = data["term_rate"]
        assert rate["rate"] is None
        assert rate["total"] == 0
        assert list(rate) == ["rate", "total", "ok", "note"]
        assert "无法计算" in rate["note"]
        assert "100%" not in rate["note"]
        assert data["terms_note"] == "没找到可对照的术语表"
    finally:
        _drop(*ids)


def test_empty_body_does_not_raise() -> None:
    """正文为空 → 不抛异常，rate=None。"""
    ids = _make_draft("", terms=TERMS)
    try:
        result = check_pack.run_check(_ctx(ids[0]))
        rate = result.data["term_rate"]
        assert rate["rate"] is None
        assert rate["total"] == 0
        assert "无法计算" in rate["note"]
        # 原有的"正文还是空的"提示也没丢
        assert "正文还是空的" in result.data["note"]
    finally:
        _drop(*ids)


def test_terms_present_but_unused_is_not_full_marks() -> None:
    """术语表非空、正文一个术语都没用 → 分母 0，仍然不是 100%。"""
    ids = _make_draft("本文只讨论实验流程。", terms=TERMS)
    try:
        rate = check_pack.run_check(_ctx(ids[0])).data["term_rate"]
        assert rate["rate"] is None
        assert rate["total"] == 0
        assert "无法计算" in rate["note"]
        assert "100%" not in rate["note"]
    finally:
        _drop(*ids)


def test_existing_numbering_findings_survive() -> None:
    """加了 term_rate 之后，编号断档那几条一条都不许少。"""
    body = "第一句[1]。第二句[3]。第三句[4]。"
    ids = _make_draft(body, orders=(1, 2, 3), terms=TERMS)
    try:
        data = check_pack.run_check(_ctx(ids[0])).data
        numbering = [
            item
            for item in data["findings"]
            if item["kind"] == "citation_number"
        ]
        assert len(numbering) == 3
        details = " ".join(item["detail"] for item in numbering)
        assert "[4]" in details
        assert "从没被引用" in details
        assert "缺号" in details
        assert data["summary"]["by_kind"]["citation_number"] == 3
        assert data["summary"]["total"] == len(data["findings"])
        assert "term_rate" in data
    finally:
        _drop(*ids)


def test_return_shape_matches_docstring() -> None:
    """键名与 docstring 一致：结构稳定，前端 / 模型照这个读。"""
    ids = _make_draft("手性中心。", terms=TERMS)
    try:
        data = check_pack.run_check(_ctx(ids[0])).data
        assert set(data) == {
            "draft_id",
            "title",
            "findings",
            "summary",
            "terms_note",
            "term_rate",
            # 该引未引（2026-10-19 接入）：一组句子 + 一句汇总
            "citation_gaps",
            "citation_gaps_note",
            "truncated",
            "note",
        }
        rate = data["term_rate"]
        assert set(rate) == {"rate", "total", "ok", "note"}
        # 顺序也钉住：前端按位置读也不会错
        assert list(rate) == ["rate", "total", "ok", "note"]
        assert isinstance(rate["rate"], float)
        assert isinstance(rate["total"], int)
        assert isinstance(rate["ok"], int)
        assert isinstance(rate["note"], str)

        doc = check_pack.run_check.__doc__ or ""
        for token in ("term_rate", "75%（3/4）", "100%"):
            assert token in doc, f"docstring 少了 {token}"
    finally:
        _drop(*ids)
