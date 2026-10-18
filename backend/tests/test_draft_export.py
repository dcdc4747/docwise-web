"""草稿导出（Markdown / Word）的回归测试。

覆盖四件事：

1. Markdown：正文**原样** + 参考文献按引文 `order` 追加，缺字段跳过（**不编**）；
2. 归属：别人的草稿一律 404（两个端点都是）；
3. Word：引擎环境没配时 **503 + 人话**，不回半成品；
4. 空草稿导出 Markdown 不炸。

⚠️ 本卡**不改 `main.py`**（路由挂载由另一处做），所以这里用"只挂本路由的独立 app"
跑用例；它不是路由挂载顺序的测试（那个归 `test_same_origin`）。
数据用 `SessionLocal` 直接造，`conftest` 每个用例重建库（天然清理）。
"""

from __future__ import annotations

from urllib.parse import unquote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from helpers import TEST_USER_ID, TEST_USERNAME, create_user_row

from app.db import SessionLocal
from app.deps import get_current_user
from app.models import Citation, Draft, Material, User
from app.routers.draft_export import router as draft_export_router
from app.services.draft_export import markdown_blocks, safe_filename

_api = FastAPI()
_api.include_router(draft_export_router)


@pytest.fixture(autouse=True)
def _signed_in():
    """独立 app 的"默认已登录"（conftest 覆盖的是 `main.app`）。"""
    fake_user = User(
        id=TEST_USER_ID,
        username=TEST_USERNAME,
        display_name="测试用户",
        password_hash="not-a-real-hash",
        role="user",
    )
    _api.dependency_overrides[get_current_user] = lambda: fake_user
    yield
    _api.dependency_overrides.clear()


# ============================================================ 造数据

def _make_draft(
    *,
    title: str = "导出测试稿",
    body_md: str = "",
    user_id: int = TEST_USER_ID,
) -> int:
    with SessionLocal() as session:
        row = Draft(user_id=user_id, title=title, body_md=body_md, template_id=None)
        session.add(row)
        session.commit()
        return row.id


def _make_material() -> int:
    with SessionLocal() as session:
        row = Material(
            user_id=TEST_USER_ID,
            text_quote="手性测度是守恒的",
            page=2,
            source_name="chem.pdf",
        )
        session.add(row)
        session.commit()
        return row.id


def _add_citation(
    draft_id: int, *, order: int, material_id: int, csl_json: dict
) -> None:
    with SessionLocal() as session:
        session.add(
            Citation(
                draft_id=draft_id,
                material_id=material_id,
                order=order,
                csl_json=csl_json,
                anchor={},
            )
        )
        session.commit()


# ============================================================ ① Markdown

BODY = (
    "# 引言\n"
    "\n"
    "本文讨论手性时间结构 [1]。\n"
    "\n"
    "## 结论\n"
    "\n"
    "如文献 [2] 所述。\n"
)


def test_markdown_export_keeps_body_and_appends_references() -> None:
    draft_id = _make_draft(title="手性综述", body_md=BODY)
    material_id = _make_material()
    # 三项齐全
    _add_citation(
        draft_id,
        order=1,
        material_id=material_id,
        csl_json={
            "title": "手性时间结构",
            "container-title": "化学学报",
            "page": "12",
        },
    )
    # 缺来源：只写标题 + 页码
    _add_citation(
        draft_id,
        order=2,
        material_id=material_id,
        csl_json={"title": "没有来源的那条", "page": "3"},
    )
    # 缺标题：只写来源 + 页码
    _add_citation(
        draft_id,
        order=3,
        material_id=material_id,
        csl_json={"container-title": "仅来源", "page": "7"},
    )
    # 三项都没有：整条跳过，不许编占位串
    _add_citation(
        draft_id, order=4, material_id=material_id, csl_json={}
    )

    with TestClient(_api) as client:
        res = client.get(f"/api/drafts/{draft_id}/export.md")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/markdown")

    # 正文原样（含 [1] / [2]），参考文献按 order 追加
    expected = (
        BODY.rstrip("\n")
        + "\n\n## 参考文献\n\n"
        + "[1] 手性时间结构. 化学学报. 12\n"
        + "[2] 没有来源的那条. 3\n"
        + "[3] 仅来源. 7"
    )
    assert res.text == expected
    assert "[4]" not in res.text  # 空条目整条不出现

    disposition = res.headers["content-disposition"]
    assert disposition.startswith("attachment; filename*=UTF-8''")
    assert unquote(disposition.split("''", 1)[1]) == "手性综述.md"


def test_markdown_export_without_citations_has_no_empty_heading() -> None:
    draft_id = _make_draft(body_md="只有正文，没有引文。")

    with TestClient(_api) as client:
        res = client.get(f"/api/drafts/{draft_id}/export.md")

    assert res.status_code == 200
    assert res.text == "只有正文，没有引文。"
    assert "参考文献" not in res.text


# ============================================================ ② 归属

def test_other_users_draft_is_404() -> None:
    other_id = create_user_row("export-other", "pw12345678")
    with SessionLocal() as session:
        row = Draft(user_id=other_id, title="别人的稿", body_md="秘密正文")
        session.add(row)
        session.commit()
        draft_id = row.id

    with TestClient(_api) as client:
        markdown = client.get(f"/api/drafts/{draft_id}/export.md")
        docx = client.get(f"/api/drafts/{draft_id}/export.docx")

    assert markdown.status_code == 404
    assert docx.status_code == 404
    # 404 时绝不泄露正文
    assert "秘密正文" not in markdown.text


# ============================================================ ③ Word 降级

def test_docx_export_without_engine_is_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DOCWISE_ENGINE_PYTHON", raising=False)
    draft_id = _make_draft(
        title="没有引擎也要说人话", body_md="# 引言\n\n引用 [1]。"
    )
    material_id = _make_material()
    _add_citation(
        draft_id,
        order=1,
        material_id=material_id,
        csl_json={"title": "文献", "page": "1"},
    )

    with TestClient(_api) as client:
        res = client.get(f"/api/drafts/{draft_id}/export.docx")

    assert res.status_code == 503
    detail = res.json()["detail"]
    assert "Word 导出需要引擎环境" in detail
    assert "DOCWISE_ENGINE_PYTHON" in detail
    # 503 只能是"说清楚"，不许挂一个空的/半成品的下载
    assert "content-disposition" not in res.headers


# ============================================================ ④ 空稿

def test_empty_draft_markdown_export_does_not_crash() -> None:
    draft_id = _make_draft(title="空稿", body_md="")

    with TestClient(_api) as client:
        res = client.get(f"/api/drafts/{draft_id}/export.md")

    assert res.status_code == 200
    assert res.text == ""
    assert res.headers["content-type"].startswith("text/markdown")
    disposition = res.headers["content-disposition"]
    # 文件名带草稿标题，说明空正文也不影响"能交稿"
    assert unquote(disposition.split("''", 1)[1]) == "空稿.md"


# ============================================================ docx 内容映射（纯函数）

def test_markdown_blocks_maps_headings_and_keeps_inline_numbers() -> None:
    blocks = markdown_blocks(
        "# 标题 [1]\n"
        "\n"
        "正文第一行 [2]\n"
        "正文第二行\n"
        "\n"
        "## 小节\n"
        "\n"
        "### 三级标题"
    )

    assert blocks == [
        {"kind": "heading", "level": 1, "text": "标题 [1]"},
        {"kind": "paragraph", "text": "正文第一行 [2]\n正文第二行"},
        {"kind": "heading", "level": 2, "text": "小节"},
        {"kind": "heading", "level": 3, "text": "三级标题"},
    ]


def test_safe_filename_replaces_unsafe_characters() -> None:
    assert safe_filename("综述: 2026/10 *初稿*", ".md") == "综述_ 2026_10 _初稿_.md"
    assert safe_filename("  ", ".docx") == "draft.docx"
    assert safe_filename("a\nb", ".md") == "a_b.md"
