"""契约闸的 CI 入口。

真正的实现是 `scripts/check_contract.py`（可命令行单跑、也能被这里调用）。

为什么把它挂进 pytest：CI 的后端 job 只跑 `ruff check .` + `pytest -q` + 健康检查，
另外加一个 step 容易在以后重排 workflow 时被漏掉；放进 pytest 就跟着现有那一步走。

它守的是：代码里的路由 与 `backend/.contract/api.json` 冻死的契约一致。
为什么普通单测抓不到这类漂移——单测跟着代码走，代码改成什么样它测什么样；
契约漂移是「代码动了、契约没动」，只有拿契约当基准才照得出来。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts.check_contract import (  # noqa: E402
    anchors_of,
    live_routes,
    load_manifest,
)


def test_contract_manifest_exists() -> None:
    """清单文件必须在，且结构完整——否则这道闸等于没有。"""
    manifest = load_manifest()
    assert manifest["anchors"], "anchors 为空：契约清单没写"
    assert isinstance(manifest["declared_endpoint_count"], int)
    assert manifest["declared_endpoint_count"] > 0


def test_anchors_all_exist_in_code() -> None:
    """冻死的锚点路由一个都不能少：改名/删掉/换方法都会在这里红。"""
    manifest = load_manifest()
    live = set(live_routes())
    missing = sorted(anchors_of(manifest) - live)
    assert not missing, (
        "以下锚点路由在代码里不存在了（契约不允许悄悄改）：\n"
        + "\n".join(f"  {method:<7} {path}" for method, path in missing)
    )


def test_no_undeclared_routes() -> None:
    """代码里不许有契约没声明的路由：新端点必须先写进契约，前端才有得对。"""
    manifest = load_manifest()
    live = set(live_routes())
    declared = anchors_of(manifest) | {
        (item["method"], item["path"]) for item in manifest.get("expected_new", [])
    }
    undeclared = sorted(live - declared)
    assert not undeclared, (
        "代码里有、契约里没声明的路由（请先更新契约与 .contract/api.json）：\n"
        + "\n".join(f"  {method:<7} {path}" for method, path in undeclared)
    )


def test_declared_endpoint_count_matches() -> None:
    """端点总数是故意冗余的一项：漏更新它，就说明「加了端点却没更新契约」。

    上面两条只比对「声明过的」：新增端点如果不写进清单，前两条会静默通过
    （没人声明它，自然既不缺也不多余）。所以总数必须另外钉一遍。
    """
    manifest = load_manifest()
    live = live_routes()
    declared = manifest["declared_endpoint_count"]
    assert len(live) == declared, (
        f"端点总数对不上：契约声明 {declared} 个，代码里实际 {len(live)} 个。\n"
        "加/删端点时，.contract/api.json 的 declared_endpoint_count 也要一起改。"
    )


@pytest.mark.parametrize("path", ["/api/health"])
def test_gate_smoke(path: str) -> None:
    """一条最小正向断言，保证 live_routes() 真读到了东西（而不是空集合）。"""
    live = {route_path for _, route_path in live_routes()}
    assert path in live, f"{path} 读不到，live_routes() 可能取不到 include 进来的路由"
