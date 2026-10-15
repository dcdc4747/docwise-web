"""收口检查接口（契约 §2.7 / N22–N23）的测试。

盯四件事：

1. ⭐ **`POST` 当场返回的报告与 `GET` 回来的逐字节一致**——
   两份不一致比没有更糟（回看时看到的和当时看到的不是一份）；
2. ⭐ **`run_id` 落库**：POST 时报告里就有（不然前端拿着一份没有编号的报告）；
3. ⭐ **归属**：别人的草稿 / 别人的报告一律 404；
4. ⭐ **报告只读**：检查**不改稿**（形态 §3.3 ②"并列摆出两处，不自动改"）。

⚠️ 不用 `tmp_path`（AGENTS.md：受限环境不可写），
用 `conftest` 那套临时库直接建行。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import TEST_USER_ID, create_user_row

from app.db import SessionLocal
from app.main import app
from app.models import CheckRun, Citation, Draft, Material
from app.timeutil import utc_now

ZH_DRAFT = (
    "本文研究酶催化反应的动力学。"
    "已有结果见[1]。"
    "研究表明，温度升高会显著加快反应速率，但选择性下降。"
    "本研究表明，该体系存在明显的补偿效应。"
)


def _make_draft(*, user_id: int = TEST_USER_ID, body_md: str = ZH_DRAFT) -> int:
    with SessionLocal() as session:
        row = Draft(
            user_id=user_id,
            title="收口用例草稿",
            body_md=body_md,
            created_at=utc_now(),
        )
        session.add(row)
        session.commit()
        return row.id


def _make_material() -> int:
    """建一张素材卡（素材的创建接口不在本卡，属另一张任务卡）。"""
    with SessionLocal() as session:
        material = Material(
            user_id=TEST_USER_ID,
            task_id=None,
            block_id="p1_b2",
            text_quote="The reaction rate rises with temperature.",
            translated_quote="反应速率随温度升高而加快，但选择性下降。",
            page=3,
            source_name="chem.pdf",
            created_at=utc_now(),
        )
        session.add(material)
        session.commit()
        return material.id


def _make_citation(draft_id: int, *, order: int = 1) -> int:
    material_id = _make_material()
    with SessionLocal() as session:
        citation = Citation(
            draft_id=draft_id,
            material_id=material_id,
            order=order,
            csl_json={
                "type": "article-journal",
                "title": "Temperature",
                "author": [{"literal": "X"}],
            },
            anchor={"offset": 0},
            created_at=utc_now(),
        )
        session.add(citation)
        session.commit()
    return material_id


def _post_check(client: TestClient, draft_id: int, text: str = ZH_DRAFT) -> dict:
    """跑一次检查（所有用例都从这里过，行宽与口径都只写一处）。"""
    response = client.post(
        "/api/check", json={"draft_id": draft_id, "doc_text": text}
    )
    return response


# ---------------------------------------------------------------- N22


def test_check_returns_report_and_persists_run():
    draft_id = _make_draft()
    _make_citation(draft_id)
    with TestClient(app) as client:
        response = _post_check(client, draft_id)
        assert response.status_code == 200
        report = response.json()

        # 形状照契约 §2.7
        assert report["run_id"]
        assert report["ruleset_version"] >= 1
        assert report["step"]["lang"] == "zh"
        assert report["step"]["citation_style"] == "numeric"
        assert set(report["summary"]) == {"reported", "unknown"}
        assert report["summary"]["reported"] >= 1

        # ⭐ 落库了：GET 拿回来的**逐字节一致**
        again = client.get(f"/api/check/{report['run_id']}")
        assert again.status_code == 200
        assert again.json() == report


def test_check_finds_missing_citation_and_suggests_material():
    draft_id = _make_draft()
    _make_citation(draft_id)
    with TestClient(app) as client:
        report = _post_check(client, draft_id).json()
        wanted = [
            item for item in report["findings"] if item["kind"] == "missing_citation"
        ]
        assert wanted, "该引未引必须报出来"
        assert "温度升高会显著加快反应速率" in wanted[0]["sentence"]
        # 素材库里有对得上的那一张 → 要挑得出来（带页码与原文）
        assert wanted[0]["suggest"]["page"] == 3
        assert wanted[0]["suggest"]["quote"]


def test_check_does_not_touch_the_draft():
    """⭐ 检查只读：不改正文（形态 §3.3 ②"不自动改"）。"""
    draft_id = _make_draft()
    with TestClient(app) as client:
        _post_check(client, draft_id, "改写过的正文，足够长到能让引擎判出语言。")
    with SessionLocal() as session:
        row = session.get(Draft, draft_id)
        assert row.body_md == ZH_DRAFT


def test_check_on_other_users_draft_is_404():
    other = create_user_row("someone-else", "pw-123456")
    draft_id = _make_draft(user_id=other)
    with TestClient(app) as client:
        assert _post_check(client, draft_id).status_code == 404


def test_check_unknown_draft_is_404():
    with TestClient(app) as client:
        assert _post_check(client, 10_000_001, "短文。").status_code == 404


def test_check_short_text_says_unknown_instead_of_nothing():
    """⭐ 判不出就不装懂：短稿 → `unknown` 一条、`reported` 为 0。"""
    draft_id = _make_draft(body_md="好。")
    with TestClient(app) as client:
        report = _post_check(client, draft_id, "好。").json()
        assert report["summary"]["reported"] == 0
        assert report["summary"]["unknown"] == 1
        assert report["findings"][0]["severity"] == "unknown"


def test_ruleset_version_is_stored_on_its_own_column():
    """版本单独存一列：以后按版本统计"哪版规则准"要筛得动。"""
    draft_id = _make_draft()
    with TestClient(app) as client:
        run_id = _post_check(client, draft_id).json()["run_id"]
    with SessionLocal() as session:
        row = session.get(CheckRun, run_id)
        assert row.ruleset_version >= 1
        assert row.lang == "zh"
        assert row.citation_style == "numeric"
        assert row.report["run_id"] == run_id


# ---------------------------------------------------------------- N23


def test_get_other_users_report_is_404():
    other = create_user_row("someone-else-2", "pw-123456")
    draft_id = _make_draft(user_id=other)
    with SessionLocal() as session:
        row = CheckRun(
            user_id=other,
            draft_id=draft_id,
            lang="zh",
            citation_style="numeric",
            ruleset_version=1,
            report={"run_id": None, "summary": {"reported": 0, "unknown": 0}},
        )
        session.add(row)
        session.commit()
        run_id = row.id
    with TestClient(app) as client:
        assert client.get(f"/api/check/{run_id}").status_code == 404


def test_get_unknown_report_is_404():
    with TestClient(app) as client:
        assert client.get("/api/check/10000002").status_code == 404
