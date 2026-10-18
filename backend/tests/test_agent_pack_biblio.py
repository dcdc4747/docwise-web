"""参考文献工具包（biblio）的用例：只读、归属、样式白名单、引擎不可用。

引擎相关的用例一律用**假引擎脚本**（`sys.executable`）：CI 上没有真引擎，
本机即使配了也不该让单测去依赖它。脚本写在 `storage.DATA_DIR`
（conftest 已把它指到临时目录），不用 `tmp_path`。
"""

from __future__ import annotations

import sys

from helpers import TEST_USER_ID

from app import storage
from app.agent.contracts import ToolContext
from app.agent.packs import biblio
from app.db import SessionLocal
from app.models import Citation, Draft, Material
from app.routers import bibliography
from app.routers.bibliography import SUPPORTED_STYLES
from app.routers.drafts import build_csl_json

# 假引擎：照真脚本的协议来（stdin JSON / stdout JSON），只回显标题
FAKE_ENGINE = '''
import json, sys

payload = json.loads(sys.stdin.read() or "{}")
items = payload.get("items", [])
out = {
    "style": "fake",
    "locale": None,
    "entries": ["[1] " + str(item.get("title")) for item in items],
    "item_texts": {},
    "count": len(items),
    "skipped": [],
}
sys.stdout.write(json.dumps(out, ensure_ascii=False))
'''

_ENGINE_ENV_KEYS = (
    "DOCWISE_ENGINE_PYTHON",
    "DOCWISE_ENGINE_SCRIPT",
    "DOCWISE_ENGINE_BIBLIOGRAPHY_SCRIPT",
)


def _ctx(*, user_id: int = TEST_USER_ID, draft_id: int | None = None) -> ToolContext:
    scope = {} if draft_id is None else {"draft_id": draft_id}
    return ToolContext(
        db=None, user_id=user_id, scene_id="write_compose", scope=scope
    )


def _make_draft(
    *, user_id: int = TEST_USER_ID, with_citation: bool = False
) -> tuple[int, int | None]:
    """建一篇草稿；需要时再建素材卡 + 一条引文（与真链路同源）。"""
    with SessionLocal() as session:
        draft = Draft(user_id=user_id, title="参考文献用例", body_md="正文")
        session.add(draft)
        session.flush()
        material_id = None
        if with_citation:
            material = Material(
                user_id=user_id,
                text_quote="the chiral measures are conserved",
                translated_quote="手性测度是守恒的",
                page=2,
                source_name="chem_arXiv.pdf",
            )
            session.add(material)
            session.flush()
            session.add(
                Citation(
                    draft_id=draft.id,
                    material_id=material.id,
                    order=1,
                    csl_json=build_csl_json(material),
                    anchor={"block_id": None, "offset": 0},
                )
            )
            material_id = material.id
        session.commit()
        return draft.id, material_id


def _cleanup(draft_id: int, material_id: int | None = None) -> None:
    with SessionLocal() as session:
        session.query(Citation).filter_by(draft_id=draft_id).delete()
        draft = session.get(Draft, draft_id)
        if draft is not None:
            session.delete(draft)
        if material_id is not None:
            material = session.get(Material, material_id)
            if material is not None:
                session.delete(material)
        session.commit()


def _clear_engine_env(monkeypatch) -> None:
    for key in _ENGINE_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    # 本机 `.env` 可能真的配了引擎，TestClient 启动时也会再注入一次；
    # 这里问的是"没配时怎么回"，所以把找脚本的函数也钉住，与机器配置无关。
    monkeypatch.setattr(bibliography, "_resolve_script", lambda: None)


def _fake_engine(monkeypatch) -> None:
    script = storage.DATA_DIR / "fake_biblio.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(FAKE_ENGINE, encoding="utf-8")
    monkeypatch.setenv("DOCWISE_ENGINE_PYTHON", sys.executable)
    monkeypatch.setenv("DOCWISE_ENGINE_BIBLIOGRAPHY_SCRIPT", str(script))
    monkeypatch.delenv("DOCWISE_ENGINE_SCRIPT", raising=False)


# ============================================================ 归属


def test_other_users_draft_is_not_found() -> None:
    """别人的草稿一律当「找不到」——越权不能靠前端拦。"""
    draft_id, _ = _make_draft(user_id=TEST_USER_ID + 999)
    try:
        got = biblio.format_bibliography(
            _ctx(), {"draft_id": draft_id, "style": "apa"}
        )
        assert got.data == {"error": "找不到这篇草稿"}
    finally:
        _cleanup(draft_id)


# ============================================================ 样式白名单


def test_unknown_style_is_refused_with_human_message() -> None:
    draft_id, _ = _make_draft()
    try:
        got = biblio.format_bibliography(
            _ctx(draft_id=draft_id), {"style": "nature"}
        )
        error = got.data["error"]
        assert "样式不支持" in error
        assert "nature" in error
        for key in SUPPORTED_STYLES:
            assert key in error
    finally:
        _cleanup(draft_id)


# ============================================================ 引擎不可用


def test_missing_engine_returns_human_error_not_exception(monkeypatch) -> None:
    """引擎没配 → `{"error": 人话}`；不抛异常、不返回半成品。"""
    _clear_engine_env(monkeypatch)
    draft_id, material_id = _make_draft(with_citation=True)
    try:
        got = biblio.format_bibliography(
            _ctx(draft_id=draft_id), {"style": "apa"}
        )
        assert set(got.data) == {"error"}
        assert "参考文献排版没跑成" in got.data["error"]
        assert "引擎" in got.data["error"]
        assert "Traceback" not in got.data["error"]
    finally:
        _cleanup(draft_id, material_id)


def test_empty_citations_return_empty_table_without_engine(monkeypatch) -> None:
    """没有引文 → 如实空表（`.data` 里不带 error），而且不需要引擎。"""
    _clear_engine_env(monkeypatch)
    draft_id, _ = _make_draft()
    try:
        got = biblio.format_bibliography(
            _ctx(draft_id=draft_id), {"style": "apa"}
        )
        assert got.data == {"style": "apa", "entries": [], "count": 0}

        # args 容错：不是 dict 也不能抛异常
        weird = biblio.format_bibliography(_ctx(), ["not", "a", "dict"])
        assert weird.data == {"error": "没有指定草稿"}
    finally:
        _cleanup(draft_id)


def test_missing_script_returns_human_error(monkeypatch) -> None:
    """脚本路径存在但文件不在 → 人话，不抛异常。"""
    monkeypatch.setenv("DOCWISE_ENGINE_PYTHON", sys.executable)
    monkeypatch.setenv(
        "DOCWISE_ENGINE_BIBLIOGRAPHY_SCRIPT",
        str(storage.DATA_DIR / "nope.py"),
    )
    monkeypatch.delenv("DOCWISE_ENGINE_SCRIPT", raising=False)
    draft_id, material_id = _make_draft(with_citation=True)
    try:
        got = biblio.format_bibliography(
            _ctx(draft_id=draft_id), {"style": "apa"}
        )
        assert set(got.data) == {"error"}
        assert "参考文献排版没跑成" in got.data["error"]
        assert "脚本不存在" in got.data["error"]
    finally:
        _cleanup(draft_id, material_id)


def test_engine_nonzero_exit_returns_human_error(monkeypatch) -> None:
    """退出码非 0 → 带上引擎自己说的话，仍然只是一句人话。"""
    script = storage.DATA_DIR / "fake_biblio_fail.py"
    script.write_text(
        "import sys\nsys.stderr.write('样式文件损坏')\nsys.exit(2)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DOCWISE_ENGINE_PYTHON", sys.executable)
    monkeypatch.setenv("DOCWISE_ENGINE_BIBLIOGRAPHY_SCRIPT", str(script))
    monkeypatch.delenv("DOCWISE_ENGINE_SCRIPT", raising=False)
    draft_id, material_id = _make_draft(with_citation=True)
    try:
        got = biblio.format_bibliography(
            _ctx(draft_id=draft_id), {"style": "apa"}
        )
        assert set(got.data) == {"error"}
        assert "参考文献排版没跑成" in got.data["error"]
        assert "退出码 2" in got.data["error"]
        assert "样式文件损坏" in got.data["error"]
    finally:
        _cleanup(draft_id, material_id)


# ============================================================ 成功路径（假引擎）


def test_success_returns_style_entries_and_count(monkeypatch) -> None:
    _fake_engine(monkeypatch)
    draft_id, material_id = _make_draft(with_citation=True)
    try:
        got = biblio.format_bibliography(
            _ctx(draft_id=draft_id), {"style": "apa"}
        )
        assert got.data["style"] == "apa"
        assert got.data["count"] == 1
        assert got.data["entries"] == ["[1] chem_arXiv.pdf"]

        # 默认样式 + scope 里的 draft_id（args=None 也要接住）
        default = biblio.format_bibliography(_ctx(draft_id=draft_id))
        assert default.data["style"] == "gb-t-7714-2015-numeric"
        assert default.data["count"] == 1

        # 只读：引文与稿子一个字节没动
        with SessionLocal() as session:
            citations = (
                session.query(Citation).filter_by(draft_id=draft_id).all()
            )
            assert len(citations) == 1
            assert citations[0].csl_json["title"] == "chem_arXiv.pdf"
            draft = session.get(Draft, draft_id)
            assert draft is not None and draft.body_md == "正文"
    finally:
        _cleanup(draft_id, material_id)
