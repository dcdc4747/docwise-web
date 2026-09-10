"""同源部署：把一个地址同时给前端与后端——后端直接托管前端构建产物。

背景：手机上访问前端时前后端不同源，得靠 `?apiBase=` 把 API 指回电脑；演示时多这
一步就容易出错。现在后端把 `frontend/dist` 挂在自己的根路径上，访问
`http://<局域网IP>:8000/` 就同时拿到页面与接口，前端 `apiUrl()` 退回相对路径，
连 CORS 都用不上了（CORS 仍保留，给 vite dev / preview 那种跨域开发态用）。

三条约定（每条都是踩过的坑）：

1. **产物不存在就不挂载**——开发态（`vite dev` + 后端）不该因为没构建而报错，
   缺产物只打一条日志，服务照常起；
2. **`/api`、`/files` 绝不参与 SPA 回退**——这两个前缀下的未知路径必须保持 JSON 404，
   回退成 HTML 会让前端的错误处理拿到一坨页面源码；同理只有浏览器导航
   （`Accept: text/html`）才配拿前端壳，拼错的 `/assets/xxx.js` 老老实实 404；
3. **不带内容指纹的入口文件（index.html / sw.js / manifest）发 `no-cache`**——
   它们更新时文件名不变，不给 `Cache-Control` 的话浏览器会按启发式缓存，
   装上 PWA 的手机最容易吃到旧壳（表现为"改完前端刷新看不到新版本"）。
"""

from __future__ import annotations

import logging
import socket
from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.routing import get_route_path
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from .config import BASE_DIR, settings

logger = logging.getLogger(__name__)

# 后端自己的前缀/路径：未知时保持 JSON 404，不回退成前端壳
BACKEND_PREFIXES = ("api/", "files/")
BACKEND_PATHS = {"docs", "redoc", "openapi.json"}

# 没有内容指纹的入口文件：每次都要让浏览器回源确认一遍
NO_CACHE_FILES = {"index.html", "sw.js", "manifest.webmanifest"}


def default_dist_dir() -> Path:
    """仓库布局下的默认产物位置：`<仓库根>/frontend/dist`。"""
    return (BASE_DIR.parent / "frontend" / "dist").resolve()


def resolve_dist_dir() -> Path | None:
    """解析要托管的前端产物目录；里面没有 index.html 就返回 None。

    `DOCWISE_FRONTEND_DIST` 可覆盖；写相对路径时按**仓库根**解析（不是按当前工作
    目录），这样从任何目录起服务结果都一致。
    """
    configured = (settings.docwise_frontend_dist or "").strip()
    if not configured:
        dist = default_dist_dir()
    else:
        dist = Path(configured).expanduser()
        if not dist.is_absolute():
            dist = BASE_DIR.parent / dist
        dist = dist.resolve()
    return dist if (dist / "index.html").is_file() else None


def lan_ipv4s() -> list[str]:
    """本机可能的局域网 IPv4（只用来打"手机怎么连"的提示）；取不到返回空列表。

    用 UDP connect 问内核"出网走哪张网卡"——不发包、不做 DNS，瞬时返回。
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))
            address = probe.getsockname()[0]
    except OSError:
        return []
    return [address] if address and not address.startswith("127.") else []


def _wants_html(scope: Scope) -> bool:
    """只有浏览器导航（Accept 带 text/html）才配拿前端壳。"""
    for key, value in scope.get("headers") or []:
        if key == b"accept":
            return b"text/html" in value.lower()
    return False


def _entry_name(path: str) -> str:
    """把挂载内的路径换算成"入口文件名"（根路径 `'.'` 就是 index.html）。"""
    return Path(path).name or "index.html"


class SpaStaticFiles(StaticFiles):
    """静态产物 + SPA 回退 + 入口文件不缓存。"""

    async def get_response(self, path: str, scope: Scope):
        served = path
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            # 注意捕获的是 **Starlette 的** HTTPException：StaticFiles 抛的是它，
            # 而 FastAPI 的那个是它的子类，写错就永远接不住 404、回退静默失效。
            if exc.status_code != 404 or not self._spa_fallback_allowed(scope):
                raise
            served = "index.html"
            response = await super().get_response(served, scope)
        if _entry_name(served) in NO_CACHE_FILES:
            response.headers["Cache-Control"] = "no-cache"
        return response

    @staticmethod
    def _spa_fallback_allowed(scope: Scope) -> bool:
        if scope.get("method") not in ("GET", "HEAD"):
            return False
        # 用 get_route_path：它已经扣掉了 root_path 前缀（挂载点内部看到的路径）
        raw = get_route_path(scope).lstrip("/")
        if raw.startswith(BACKEND_PREFIXES) or raw in BACKEND_PATHS:
            return False
        return _wants_html(scope)


def mount_frontend(app: FastAPI, dist_dir: Path | None = None) -> bool:
    """把前端产物挂到应用根路径，返回是否真的挂上了。

    **必须在所有 API 路由注册完之后调用**：Starlette 按注册顺序匹配，挂载点写在
    前面会把后面注册的 `/api/...` 一起吃进静态文件（表现为接口全变 404/HTML）。
    """
    if not settings.docwise_serve_frontend:
        logger.info("DOCWISE_SERVE_FRONTEND 已关闭：本进程只提供 API")
        return False

    dist = dist_dir or resolve_dist_dir()
    if dist is None or not (dist / "index.html").is_file():
        logger.info(
            "未找到前端产物（%s），本进程只提供 API；要一个地址同源访问，"
            "请先在 frontend/ 下构建",
            dist or default_dist_dir(),
        )
        return False

    app.mount("/", SpaStaticFiles(directory=str(dist), html=True), name="frontend")
    logger.info("已托管前端产物：%s（访问 / 即打开应用，同源，不用拼 ?apiBase=）", dist)
    addresses = lan_ipv4s()
    if addresses:
        logger.info(
            "手机/他人电脑访问：以 --host 0.0.0.0 启动，再打开 http://%s:<端口>/"
            "（端口 = --port 的值；本机局域网地址：%s）",
            addresses[0],
            "、".join(addresses),
        )
    return True
