"""契约闸：比对「冻死的接口契约清单」与「代码里真实存在的路由」。

用法（在 backend/ 下跑，走 uv 或 .venv 里的 python）：

    python scripts/check_contract.py             # 检查，不一致就退出码 1
    python scripts/check_contract.py --print     # 打印 /api 路由清单
    python scripts/check_contract.py --print-all # 连非 /api 的一起打（排查用）

为什么要有它：契约（docs/契约_接口_v1_20261014.md）冻的是「前端照着写」的接口面。
一旦代码与契约漂移——路由改名、方法换掉、端点被删——前端的 mock 会继续「对」，
而真接口已经变了。这类问题普通单测抓不到：单测跟着代码走，代码改成什么样它测什么样；
**只有拿契约当基准，才照得出「代码动了、契约没动」。**

⚠️ 踩过的坑（别照直觉遍历 `app.routes`）：本项目这份 FastAPI 把 `include_router`
注册出来的路由包成 `_IncludedRouter` 对象——它既没有 `path`、也没有 `routes`
（真正的路由挂在私有属性 `original_router` 上，前缀在 `include_context` 里）。
第一版脚本遍历 `app.routes` 再取 `path`，只数到 `/api/health` 一个，
其余 24 个被静默跳过；第二版试着递归 `routes` 仍然只拿到 1 个。
差点据此得出「契约没错」的结论。
→ 正解：**用 `app.openapi()`**。它由 FastAPI 自己生成，会把 include 进来的路由铺平、
前缀也拼好，是公开且稳定的口径——不要摸 `_IncludedRouter` 的私有属性。

清单文件：`backend/.contract/api.json`

- `anchors`：冻死的路由，一个个手写。想改必须先改这里——契约漂移要有人签字。
- `declared_endpoint_count`：端点总数。故意手写、故意冗余：加删端点时这里也要改，
  防的是「偷偷加了端点却没更新契约」——那是前端对着 mock 写完才发现形状不对的根源。
- `expected_new`：契约里冻了、代码还没实现的新端点。没实现不算失败；
  一旦实现了会提示「可以从 expected_new 移进 anchors 了」。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
MANIFEST = BACKEND_DIR / ".contract" / "api.json"

# 直接 `python scripts/check_contract.py` 跑时，sys.path 里没有 backend/，
# 上面的 import 会 ModuleNotFoundError（pytest 从 backend 根跑，所以没这问题）。
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 这些方法不参与比对：FastAPI 给每个 GET 路由自动挂 HEAD，OPTIONS 由 CORS 处理
IGNORED_METHODS = {"HEAD", "OPTIONS"}


def _normalize(path: str) -> str:
    """把 FastAPI 的路径参数写法统一成契约里的写法（{param}）。

    这样「把 task_id 改名成 id」不会被误报成新增端点；改名本身靠 review 抓。
    """
    out = []
    for chunk in path.split("/"):
        if chunk.startswith("{") and chunk.endswith("}"):
            out.append("{param}")
        else:
            out.append(chunk)
    return "/".join(out)


def _direct_routes(acc: list) -> None:
    """把 `app.routes` 里直接挂载的路由收进来（include 进来的取不到，见模块文档）。"""
    from app.main import app

    for route in app.routes:
        path = getattr(route, "path", None)
        if not path:
            continue
        for method in sorted(getattr(route, "methods", []) or []):
            if method in IGNORED_METHODS:
                continue
            acc.append((method, path, "direct"))


def all_routes() -> list[tuple[str, str, str]]:
    """(method, path, 来源) 全量列表，来源 = openapi / direct，便于排查。

    两路取并集：`app.openapi()` 是主力（include 的路由已铺平）；
    再叠一边直接挂载的，把 openapi 不收的东西也带上。
    """
    from app.main import app

    acc: list[tuple[str, str, str]] = []

    schema = app.openapi()
    for path, methods in (schema.get("paths") or {}).items():
        for method in methods:
            upper = method.upper()
            if upper in IGNORED_METHODS:
                continue
            acc.append((upper, path, "openapi"))

    _direct_routes(acc)
    return sorted(set(acc))


def live_routes(include_non_api: bool = False) -> list[tuple[str, str]]:
    """代码里真实存在的 (method, path)，路径参数已归一化。"""
    rows = {
        (method, _normalize(path))
        for method, path, _ in all_routes()
        if include_non_api or path.startswith("/api")
    }
    return sorted(rows)


def load_manifest() -> dict:
    if not MANIFEST.exists():
        raise SystemExit(f"找不到契约清单：{MANIFEST}")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def anchors_of(manifest: dict) -> set[tuple[str, str]]:
    return {(item["method"], item["path"]) for item in manifest["anchors"]}


def expected_new_of(manifest: dict) -> set[tuple[str, str]]:
    return {(item["method"], item["path"]) for item in manifest.get("expected_new", [])}


def check() -> int:
    manifest = load_manifest()
    live = set(live_routes())
    anchors = anchors_of(manifest)
    expected_new = expected_new_of(manifest)
    declared = manifest["declared_endpoint_count"]

    problems: list[str] = []

    missing = sorted(anchors - live)
    if missing:
        problems.append(
            "以下锚点路由在代码里不存在（改名/删掉/方法换了？契约不允许悄悄改）：\n"
            + "\n".join(f"    {m:<7} {p}" for m, p in missing)
        )

    undeclared = sorted(live - anchors - expected_new)
    if undeclared:
        problems.append(
            "代码里有、但契约里没声明的路由（新端点必须先进契约）：\n"
            + "\n".join(f"    {m:<7} {p}" for m, p in undeclared)
        )

    implemented = sorted(live & expected_new)
    if implemented:
        print(
            "提示：以下端点已实现，可以从 expected_new 移进 anchors 了：\n"
            + "\n".join(f"    {m:<7} {p}" for m, p in implemented)
        )

    if len(live) != declared:
        problems.append(
            f"端点总数对不上：契约声明 {declared} 个，代码里实际 {len(live)} 个。\n"
            "    （加/删端点时，清单里的 declared_endpoint_count 也要一起改——"
            "这一条是故意冗余的，防的是偷偷加了端点却没更新契约）"
        )

    if problems:
        print("契约闸：不通过\n")
        for item in problems:
            print(f"  x {item}\n")
        print(f"清单：{MANIFEST}")
        print(f"  锚点 {len(anchors)} / 待实现 {len(expected_new)} / 实测 {len(live)}")
        return 1

    print("契约闸：通过")
    print(
        f"  锚点 {len(anchors)} 个全部在 / 待实现 {len(expected_new)} 个"
        f" / 代码里共 {len(live)} 个 = 声明的 {declared} 个"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="接口契约与代码的一致性检查")
    parser.add_argument(
        "--print", dest="do_print", action="store_true", help="打印 /api 路由清单"
    )
    parser.add_argument(
        "--print-all",
        dest="do_print_all",
        action="store_true",
        help="打印全部路由（含非 /api 的），排查注册问题用",
    )
    args = parser.parse_args()

    if args.do_print_all:
        from app.main import app

        rows = all_routes()
        print(f"取到路由 {len(rows)} 条（openapi + 直接挂载的并集）：")
        for method, path, kind in rows:
            print(f"  {kind:<8} {method:<7} {path}")
        paths = app.openapi().get("paths") or {}
        print(f"\napp.routes 顶层 {len(app.routes)} 条；openapi paths {len(paths)} 个")
        return 0

    if args.do_print:
        rows = live_routes()
        for method, path in rows:
            print(f"{method:<7} {path}")
        print(f"---\n共 {len(rows)} 个（不含 HEAD/OPTIONS）")
        return 0

    return check()


if __name__ == "__main__":
    sys.exit(main())
