"""参考文献格式化（契约 §2.6 / N31）的测试。

⭐ 用**假引擎脚本**跑（`sys.executable`），**不依赖真引擎 venv** —— CI 上没有引擎。
脚本写在 `storage.DATA_DIR`（conftest 已把它指到临时目录），**不用 `tmp_path`**
（AGENTS.md：受限环境不可写）。

盯五件最容易写坏的事：

1. ⭐ **中文 UTF-8 往返**：Windows 上子进程默认按 GBK 读写，中文会变成孤立代理字符；
2. ⭐ **item 原样透传**：喂给引擎的 stdin 里就是 `citations.csl_json` 本身（id 约定
   `material-{id}`），一个字段都不许在这里"顺手修"；
3. ⭐ **`styles` 是后端追加的**（引擎不管这个字段）；
4. ⭐ **没有引文不白跑引擎**：200 空表，而且**不需要引擎环境**；
5. ⭐ **引擎不可用一律 503 + 人话**：未配置 / 脚本不存在 / 退出码非 0 / 超时 /
   输出不是 JSON —— **不给半成品**。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from helpers import TEST_USER_ID, create_user_row

from app import storage
from app.db import SessionLocal
from app.main import app
from app.models import Citation, Draft, Material
from app.routers import bibliography
from app.routers.bibliography import SUPPORTED_STYLES
from app.routers.drafts import build_csl_json
from app.timeutil import utc_now

# 假引擎：照真脚本的协议来（stdin JSON / stdout JSON），另外支持三种"坏"模式
FAKE = '''
import json, os, sys, time

mode = os.environ.get("FAKE_BIB_MODE", "ok")
if mode == "sleep":
    time.sleep(5)
if mode == "garbage":
    sys.stdout.write("这不是 JSON")
    sys.exit(0)
if mode == "fail":
    sys.stderr.write("样式文件损坏：apa.csl 读不了")
    sys.exit(2)

payload = json.loads(sys.stdin.read() or "{}")
echo = os.environ.get("FAKE_BIB_ECHO")
if echo:
    with open(echo, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)

items = payload.get("items", [])
out = {
    "style": "fake",
    "locale": None,
    "entries": ["[1] 中文条目：" + str(item.get("title")) for item in items],
    "item_texts": {
        item.get("id"): "中文条目：" + str(item.get("title")) for item in items
    },
    "count": len(items),
    "skipped": [],
}
sys.stdout.write(json.dumps(out, ensure_ascii=False))
'''


def _fake_engine(
    monkeypatch,
    *,
    mode: str = "ok",
    echo: Path | None = None,
    name: str = "fake_bibliography.py",
) -> Path:
    """把假引擎脚本指给后端（写完返回脚本路径）。"""
    script = storage.DATA_DIR / name
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(FAKE, encoding="utf-8")
    monkeypatch.setenv("DOCWISE_ENGINE_PYTHON", sys.executable)
    monkeypatch.setenv("DOCWISE_ENGINE_BIBLIOGRAPHY_SCRIPT", str(script))
    monkeypatch.setenv("FAKE_BIB_MODE", mode)
    if echo is not None:
        monkeypatch.setenv("FAKE_BIB_ECHO", str(echo))
    return script


def _clear_engine_env(monkeypatch) -> None:
    for key in (
        "DOCWISE_ENGINE_PYTHON",
        "DOCWISE_ENGINE_SCRIPT",
        "DOCWISE_ENGINE_BIBLIOGRAPHY_SCRIPT",
    ):
        monkeypatch.delenv(key, raising=False)


def _make_draft_with_citation(
    *, user_id: int = TEST_USER_ID, source_name: str = "chem_arXiv.pdf"
) -> tuple[int, int]:
    """建素材 + 草稿 + 一条引文（`csl_json` 走 `build_csl_json`，与真链路同源）。"""
    with SessionLocal() as session:
        material = Material(
            user_id=user_id,
            task_id=None,
            block_id=None,
            text_quote="the chiral measures are conserved",
            translated_quote="手性测度是守恒的",
            page=2,
            source_name=source_name,
            created_at=utc_now(),
        )
        session.add(material)
        session.commit()
        draft = Draft(user_id=user_id, title="综述初稿", body_md="")
        session.add(draft)
        session.commit()
        session.add(
            Citation(
                draft_id=draft.id,
                material_id=material.id,
                order=1,
                csl_json=build_csl_json(material),
                anchor={"block_id": None, "offset": 0},
            )
        )
        session.commit()
        return draft.id, material.id


def _make_empty_draft(*, user_id: int = TEST_USER_ID) -> int:
    with SessionLocal() as session:
        draft = Draft(user_id=user_id, title="还没引文献", body_md="")
        session.add(draft)
        session.commit()
        return draft.id


# ============================================================ 成功路径


def test_success_passes_csl_items_and_appends_styles(monkeypatch) -> None:
    """⭐ 喂给引擎的就是 `csl_json` 本身；`styles` 是后端追加的。"""
    draft_id, material_id = _make_draft_with_citation()
    echo = storage.DATA_DIR / "bib-stdin.json"
    _fake_engine(monkeypatch, echo=echo)

    with TestClient(app) as client:
        resp = client.get(
            f"/api/drafts/{draft_id}/bibliography", params={"style": "apa"}
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["styles"] == list(SUPPORTED_STYLES)  # 引擎不管这个字段
    assert body["count"] == 1
    assert body["item_texts"][f"material-{material_id}"] == "中文条目：chem_arXiv.pdf"
    assert body["entries"] == ["[1] 中文条目：chem_arXiv.pdf"]

    sent = json.loads(echo.read_text(encoding="utf-8"))
    assert [item["id"] for item in sent["items"]] == [f"material-{material_id}"]
    with SessionLocal() as session:
        stored = session.query(Citation).one().csl_json
    assert sent["items"][0] == stored  # 原样透传，一个字段都没动


def test_chinese_survives_the_round_trip(monkeypatch) -> None:
    """⭐ 中文往返：子进程若按 GBK 读写，这里会变成乱码/孤立代理字符。"""
    draft_id, _ = _make_draft_with_citation(source_name="中文文献名.pdf")
    _fake_engine(monkeypatch)

    with TestClient(app) as client:
        resp = client.get(
            f"/api/drafts/{draft_id}/bibliography", params={"style": "ieee"}
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["entries"] == ["[1] 中文条目：中文文献名.pdf"]
    text = json.dumps(body, ensure_ascii=False)
    assert "\ufffd" not in text  # 没有替换字符（GBK 事故的指纹）


def test_script_can_be_derived_from_the_translation_script_dir(monkeypatch) -> None:
    """没配专属变量时，按 `DOCWISE_ENGINE_SCRIPT` 的**同目录**找
    `run_bibliography.py`。"""
    draft_id, _ = _make_draft_with_citation()
    _fake_engine(monkeypatch, name="run_bibliography.py")
    monkeypatch.delenv("DOCWISE_ENGINE_BIBLIOGRAPHY_SCRIPT", raising=False)
    monkeypatch.setenv(
        "DOCWISE_ENGINE_SCRIPT", str(storage.DATA_DIR / "run_translation.py")
    )

    with TestClient(app) as client:
        resp = client.get(
            f"/api/drafts/{draft_id}/bibliography", params={"style": "apa"}
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["count"] == 1


def test_no_citations_returns_empty_table_without_engine(monkeypatch) -> None:
    """⭐ 没有引文 → 200 空表，**而且不需要引擎环境**（不白跑、也不是 503）。"""
    _clear_engine_env(monkeypatch)
    draft_id = _make_empty_draft()

    with TestClient(app) as client:
        resp = client.get(
            f"/api/drafts/{draft_id}/bibliography", params={"style": "apa"}
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["entries"] == []
    assert body["item_texts"] == {}
    assert body["count"] == 0
    assert body["skipped"] == []
    assert body["styles"] == list(SUPPORTED_STYLES)


# ============================================================ 引擎不可用 → 503


def test_unconfigured_engine_is_503_with_human_message(monkeypatch) -> None:
    _clear_engine_env(monkeypatch)
    # ⚠️ 只清环境变量**不够**：`TestClient(app)` 启动时会从 `.env` 再注入一次，
    #    而本机同目录**真的存在** `run_bibliography.py` → 会真去调引擎、这条就假红。
    #    本用例问的是"**没配引擎时**怎么回"，所以直接钉住解析函数，与机器配置无关。
    monkeypatch.setattr(bibliography, "_resolve_script", lambda: None)
    draft_id, _ = _make_draft_with_citation()

    with TestClient(app) as client:
        resp = client.get(
            f"/api/drafts/{draft_id}/bibliography", params={"style": "apa"}
        )

    assert resp.status_code == 503, resp.text
    assert "DOCWISE_ENGINE" in resp.json()["detail"]


def test_missing_script_is_503(monkeypatch) -> None:
    draft_id, _ = _make_draft_with_citation()
    monkeypatch.setenv("DOCWISE_ENGINE_PYTHON", sys.executable)
    monkeypatch.setenv(
        "DOCWISE_ENGINE_BIBLIOGRAPHY_SCRIPT", str(storage.DATA_DIR / "nope.py")
    )

    with TestClient(app) as client:
        resp = client.get(
            f"/api/drafts/{draft_id}/bibliography", params={"style": "apa"}
        )

    assert resp.status_code == 503, resp.text
    assert "不存在" in resp.json()["detail"]


def test_nonzero_exit_is_503_and_carries_engine_words(monkeypatch) -> None:
    """退出码非 0 → 503，**detail 里带上引擎自己说的话**（可诊断，不吞掉）。"""
    draft_id, _ = _make_draft_with_citation()
    _fake_engine(monkeypatch, mode="fail")

    with TestClient(app) as client:
        resp = client.get(
            f"/api/drafts/{draft_id}/bibliography", params={"style": "apa"}
        )

    assert resp.status_code == 503, resp.text
    detail = resp.json()["detail"]
    assert "退出码 2" in detail
    assert "样式文件损坏" in detail


def test_timeout_is_503(monkeypatch) -> None:
    """超时按失败报（不无声无息挂着）。"""
    draft_id, _ = _make_draft_with_citation()
    _fake_engine(monkeypatch, mode="sleep")
    monkeypatch.setattr(bibliography, "_TIMEOUT_SECONDS", 1)

    with TestClient(app) as client:
        resp = client.get(
            f"/api/drafts/{draft_id}/bibliography", params={"style": "apa"}
        )

    assert resp.status_code == 503, resp.text
    assert "超时" in resp.json()["detail"]


def test_non_json_output_is_503(monkeypatch) -> None:
    draft_id, _ = _make_draft_with_citation()
    _fake_engine(monkeypatch, mode="garbage")

    with TestClient(app) as client:
        resp = client.get(
            f"/api/drafts/{draft_id}/bibliography", params={"style": "apa"}
        )

    assert resp.status_code == 503, resp.text
    assert "不是 JSON" in resp.json()["detail"]


# ============================================================ 入参与归属


def test_invalid_style_is_400_and_lists_the_keys(monkeypatch) -> None:
    _clear_engine_env(monkeypatch)
    draft_id, _ = _make_draft_with_citation()

    with TestClient(app) as client:
        resp = client.get(
            f"/api/drafts/{draft_id}/bibliography", params={"style": "nature"}
        )

    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert "nature" in detail
    for key in SUPPORTED_STYLES:
        assert key in detail


def test_missing_style_is_400(monkeypatch) -> None:
    """没传样式 → 400（不是 422，也不是"随便挑一个默认样式"）。"""
    _clear_engine_env(monkeypatch)
    draft_id, _ = _make_draft_with_citation()

    with TestClient(app) as client:
        resp = client.get(f"/api/drafts/{draft_id}/bibliography")

    assert resp.status_code == 400, resp.text
    assert "样式 key" in resp.json()["detail"]


def test_other_users_draft_is_404(monkeypatch) -> None:
    other_id = create_user_row("other-user", "pw-12345678")
    draft_id, _ = _make_draft_with_citation(user_id=other_id)
    _fake_engine(monkeypatch)

    with TestClient(app) as client:
        resp = client.get(
            f"/api/drafts/{draft_id}/bibliography", params={"style": "apa"}
        )

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "草稿不存在"


def test_csl_titles_lose_the_storage_hash_prefix() -> None:
    """⭐ 引用条目里不许出现上传落盘的哈希前缀（`{32位hex}_原名`）。

    素材是"创建时快照"，老引文的 `csl_json` 里已经存了带哈希的名字；
    出参统一洗一遍，用户看到的条目才是干净文件名（不用迁移、不用重插引文）。
    """
    from app.routers.bibliography import _clean_csl

    dirty = {
        "id": "material-1",
        "title": "1236dde973c54bb1abc08afd55495989_math_arXiv_2609.38101v1.pdf",
        "container-title": "abcdefabcdefabcdefabcdefabcdef12_期刊名.pdf",
        "page": 3,
    }
    clean = _clean_csl(dirty)
    assert clean["title"] == "math_arXiv_2609.38101v1.pdf"
    assert clean["container-title"] == "期刊名.pdf"
    # 非字符串字段原样保留
    assert clean["page"] == 3
    # 前端自己起的名字（没有 32 位哈希）一个字都不动
    assert _clean_csl({"title": "2026_年度报告.pdf"})["title"] == "2026_年度报告.pdf"
