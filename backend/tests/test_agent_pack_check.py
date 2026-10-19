"""`check` 工具包的用例：编号断档 / 空引用措辞 / 越权 / 术语混用。

⚠️ 这里没有 db_session fixture：自己开 `SessionLocal` 造数据，跑完删掉。
只读工具**不许**在库里留下任何东西，第一条用例顺手把这条也钉住。
"""

from __future__ import annotations

import json

from helpers import TEST_USER_ID

from app.agent.contracts import ToolContext
from app.agent.packs import check as check_pack
from app.db import SessionLocal
from app.models import (
    CheckRun,
    Citation,
    Draft,
    Material,
    Task,
    TaskUnderstanding,
)


def _ctx(draft_id=None) -> ToolContext:
    scope = {} if draft_id is None else {"draft_id": draft_id}
    return ToolContext(
        db=None,
        user_id=TEST_USER_ID,
        scene_id="write_compose",
        scope=scope,
    )


def _make_draft(body: str, orders: tuple[int, ...] = ()) -> tuple[int, int]:
    """建一篇本人的草稿（引文都挂在同一张素材卡上）。"""
    with SessionLocal() as session:
        material = Material(
            user_id=TEST_USER_ID,
            text_quote="引文依据",
            page=1,
            source_name="sample.pdf",
        )
        session.add(material)
        session.flush()
        draft = Draft(user_id=TEST_USER_ID, title="检查用例", body_md=body)
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
        return draft.id, material.id


def _drop(draft_id: int, material_id: int) -> None:
    """删掉用例造的数据（先删引文，再删草稿与素材）。"""
    with SessionLocal() as session:
        session.query(Citation).filter_by(draft_id=draft_id).delete()
        draft = session.get(Draft, draft_id)
        if draft is not None:
            session.delete(draft)
        material = session.get(Material, material_id)
        if material is not None:
            session.delete(material)
        session.commit()


def test_citation_numbering_reports_missing_and_gap() -> None:
    """引用了不存在的号 / 文献表条目没人引 / 编号跳号，一次全报出来。"""
    body = "第一句[1]。第二句[3]。第三句[4]。"
    draft_id, material_id = _make_draft(body, orders=(1, 2, 3))
    try:
        result = check_pack.run_check(_ctx(draft_id))
        data = result.data
        numbering = [
            item
            for item in data["findings"]
            if item["kind"] == "citation_number"
        ]
        assert len(numbering) == 3
        details = " ".join(item["detail"] for item in numbering)
        assert "[4]" in details            # 引用了不存在的号
        assert "从没被引用" in details      # 文献表第 2 条没人引
        assert "缺号" in details           # 编号跳号
        assert data["summary"]["by_kind"]["citation_number"] == 3
        assert data["summary"]["total"] == len(data["findings"])
        assert "需要看一眼" in result.note
        # 有引文、但素材没挂到任何 task → 追不到术语表，如实说
        assert data["terms_note"] == "没找到可对照的术语表"

        # args 写坏了不该崩：退回 scope 里那篇
        tolerant = check_pack.run_check(
            _ctx(draft_id), {"draft_id": "不是数字"}
        )
        assert tolerant.data["draft_id"] == draft_id

        # 只读：不落 CheckRun
        with SessionLocal() as session:
            assert session.query(CheckRun).count() == 0
    finally:
        _drop(draft_id, material_id)


def test_unsourced_claim_phrases_are_reported() -> None:
    """「相关研究表明 / 数据显示」这种空引用措辞要逐句列出来。"""
    body = "相关研究表明，这种方式明显更好。数据显示，它还更便宜。"
    draft_id, material_id = _make_draft(body)
    try:
        result = check_pack.run_check(_ctx(draft_id), None)
        findings = [
            item
            for item in result.data["findings"]
            if item["kind"] == "unsourced_claim"
        ]
        assert len(findings) == 2
        details = " ".join(item["detail"] for item in findings)
        assert "相关研究表明" in details
        assert "数据显示" in details
        assert result.data["summary"]["by_kind"]["citation_number"] == 0
        assert "2 处需要看一眼" in result.note
    finally:
        _drop(draft_id, material_id)


def test_other_users_draft_looks_missing() -> None:
    """别人的草稿当"找不到"——越权不能靠前端拦。"""
    with SessionLocal() as session:
        other = Draft(
            user_id=TEST_USER_ID + 999,
            title="别人的稿",
            body_md="相关研究表明，这不该被看到。",
        )
        session.add(other)
        session.commit()
        session.refresh(other)
        other_id = other.id
    try:
        result = check_pack.run_check(_ctx(other_id))
        assert "找不到" in str(result.data)
    finally:
        with SessionLocal() as session:
            session.delete(session.get(Draft, other_id))
            session.commit()


def test_term_mixing_between_original_and_translation() -> None:
    """同一术语的原文与中文译名在正文里同现 → 术语不一致。"""
    with SessionLocal() as session:
        task = Task(
            user_id=TEST_USER_ID,
            filename="术语来源.pdf",
            status="completed",
        )
        session.add(task)
        session.flush()
        session.add(
            TaskUnderstanding(
                task_id=task.id,
                terms_json=json.dumps(
                    [{"term": "chiral", "cn": "手性"}],
                    ensure_ascii=False,
                ),
                status="ready",
            )
        )
        material = Material(
            user_id=TEST_USER_ID,
            task_id=task.id,
            text_quote="chiral measures are conserved",
            page=2,
            source_name="术语来源.pdf",
        )
        session.add(material)
        session.flush()
        draft = Draft(
            user_id=TEST_USER_ID,
            title="术语用例",
            body_md="手性是该体系的核心。chiral 这个词也出现了[1]。",
        )
        session.add(draft)
        session.flush()
        session.add(
            Citation(
                draft_id=draft.id,
                material_id=material.id,
                order=1,
                csl_json={
                    "type": "article-journal",
                    "title": "术语来源",
                    "author": [{"literal": "X"}],
                },
                anchor={"offset": 0},
            )
        )
        session.commit()
        draft_id, material_id, task_id = draft.id, material.id, task.id
    try:
        result = check_pack.run_check(_ctx(draft_id))
        terms = [
            item
            for item in result.data["findings"]
            if item["kind"] == "term_inconsistent"
        ]
        assert len(terms) == 1
        assert "chiral" in terms[0]["detail"]
        assert "手性" in terms[0]["detail"]
        assert result.data["terms_note"] == "对照了 1 条术语"
    finally:
        _drop(draft_id, material_id)
        with SessionLocal() as session:
            session.query(TaskUnderstanding).filter_by(
                task_id=task_id
            ).delete()
            session.delete(session.get(Task, task_id))
            session.commit()


def test_pack_exposes_single_read_only_tool() -> None:
    """插件发现：pack 名 `check`，只挂一个 `run_check`。"""
    from app.agent import registry

    registry.reset_cache()
    pack = registry.packs()["check"]
    assert pack.name == "check"
    assert [tool.name for tool in pack.tools] == ["run_check"]
    assert pack.tools[0].handler is check_pack.run_check
