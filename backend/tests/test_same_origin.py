"""同源部署（后端托管前端产物）的回归测试。

重点不是"能不能读到 index.html"，而是三条容易翻车的约定：
① `/api`、`/files` 下的未知路径**绝不能**被 SPA 回退成 HTML（前端会拿到一坨页面源码）；
② 只有浏览器导航（`Accept: text/html`）才回退，拼错的静态资源要老老实实 404；
③ 挂载点必须排在所有 API 路由之后（顺序写错的表现是"接口全 404/变 HTML"）。
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.routing import Mount

from app import webapp
from app.config import settings
from app.main import app

SHELL_MARKER = "DOCWISE_TEST_SHELL"


def _make_dist() -> Path:
    """造一个假的构建产物目录（不用 tmp_path：受限环境里它不可写）。"""
    dist = Path(tempfile.gettempdir()) / f"docwise_dist_{uuid.uuid4().hex}"
    (dist / "assets").mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text(
        f"<!doctype html><div id='app'>{SHELL_MARKER}</div>", encoding="utf-8"
    )
    (dist / "assets" / "app.js").write_text(
        "console.log('docwise')\n", encoding="utf-8"
    )
    (dist / "sw.js").write_text("// docwise sw\n", encoding="utf-8")
    (dist / "manifest.webmanifest").write_text('{"name": "docwise"}', encoding="utf-8")
    return dist


def _app_with_backend_routes() -> FastAPI:
    """一个"和线上同构"的最小应用：API 路由 + `/files`，最后才挂静态产物。"""
    api = FastAPI()

    @api.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @api.get("/files/{name}")
    def files(name: str) -> dict[str, str]:
        return {"name": name}

    return api


@pytest.fixture
def mounted_client() -> TestClient:
    api = _app_with_backend_routes()
    assert webapp.mount_frontend(api, dist_dir=_make_dist()) is True
    return TestClient(api)


def test_serves_shell_and_assets(mounted_client: TestClient) -> None:
    shell = mounted_client.get("/")
    assert shell.status_code == 200
    assert SHELL_MARKER in shell.text
    assert shell.headers["content-type"].startswith("text/html")

    asset = mounted_client.get("/assets/app.js")
    assert asset.status_code == 200
    assert "docwise" in asset.text


def test_api_routes_are_not_shadowed_by_mount(mounted_client: TestClient) -> None:
    """`/api`、`/files` 必须还是后端的，未知路径保持 JSON 404（不是前端壳）。"""
    assert mounted_client.get("/api/health").json() == {"status": "ok"}
    assert mounted_client.get("/files/mono").json() == {"name": "mono"}

    for path in ("/api/definitely-not-a-route", "/files/mono/missing"):
        response = mounted_client.get(path, headers={"Accept": "text/html"})
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json"), path
        assert SHELL_MARKER not in response.text


def test_spa_fallback_only_for_browser_navigation(mounted_client: TestClient) -> None:
    deep_link = mounted_client.get("/deep/link", headers={"Accept": "text/html"})
    assert deep_link.status_code == 200
    assert SHELL_MARKER in deep_link.text

    # 不是导航（没有 text/html）就别给壳：拼错的静态资源要 404 得清清楚楚
    fetch = mounted_client.get("/deep/link", headers={"Accept": "*/*"})
    assert fetch.status_code == 404
    missing_asset = mounted_client.get("/assets/missing.js", headers={"Accept": "*/*"})
    assert missing_asset.status_code == 404
    assert SHELL_MARKER not in missing_asset.text


def test_entry_files_are_not_cacheable(mounted_client: TestClient) -> None:
    """入口文件不带内容指纹，必须让浏览器每次回源（否则装上 PWA 的手机吃旧壳）。"""
    for path in ("/", "/index.html", "/sw.js", "/manifest.webmanifest"):
        response = mounted_client.get(path)
        assert response.status_code == 200, path
        assert response.headers.get("cache-control") == "no-cache", path

    # 构建产物带 hash，不需要额外的 no-cache（保持静态托管的默认行为）
    assert "cache-control" not in mounted_client.get("/assets/app.js").headers


def test_skips_mounting_when_build_is_missing() -> None:
    empty = Path(tempfile.gettempdir()) / f"docwise_dist_empty_{uuid.uuid4().hex}"
    empty.mkdir(parents=True, exist_ok=True)

    api = _app_with_backend_routes()
    # 目录里没有 index.html、目录压根不存在，都不该抛异常、也不该挂载
    assert webapp.mount_frontend(api, dist_dir=empty) is False
    assert webapp.mount_frontend(api, dist_dir=empty / "nope") is False
    # 没挂上时 API 照旧
    assert TestClient(api).get("/api/health").json() == {"status": "ok"}


def test_serve_frontend_can_be_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "docwise_serve_frontend", False)
    api = _app_with_backend_routes()
    assert webapp.mount_frontend(api, dist_dir=_make_dist()) is False
    assert not any(isinstance(route, Mount) for route in api.router.routes)


def test_real_app_mounts_frontend_after_every_api_route() -> None:
    """线上应用的结构性约定：静态挂载之后不许再有 /api、/files 路由。"""
    routes = app.router.routes
    mount_indexes = [i for i, route in enumerate(routes) if isinstance(route, Mount)]
    if not mount_indexes:
        # 本环境没构建产物（CI 里就是），跳过顺序检查——机制本身已被上面的用例覆盖
        return
    shadowed = [
        getattr(route, "path", "")
        for route in routes[max(mount_indexes) + 1 :]
        if getattr(route, "path", "").startswith(("/api", "/files"))
    ]
    assert shadowed == [], f"这些路由排在静态挂载之后，会被静态文件吃掉：{shadowed}"


def test_real_app_health_is_still_json() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
