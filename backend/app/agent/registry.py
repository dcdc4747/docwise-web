"""插件发现：扫 `packs/*.py` 与 `scenes/*.py` 里的 `PACK` / `SCENE`。

**core 里没有任何 if/import**：加一个包或一个场景 = 新建一个文件。
（这条是整个"接新功能只加文件"的落地点，别改成手写注册表。）
"""

from __future__ import annotations

import importlib
import pkgutil
from functools import lru_cache

from .contracts import Pack, Scene

_PACK_PKG = "app.agent.packs"
_SCENE_PKG = "app.agent.scenes"


def _iter_modules(package_name: str):
    package = importlib.import_module(package_name)
    for info in pkgutil.iter_modules(package.__path__):
        if info.name.startswith("_"):
            continue
        yield importlib.import_module(f"{package_name}.{info.name}")


@lru_cache(maxsize=1)
def packs() -> dict[str, Pack]:
    found: dict[str, Pack] = {}
    for module in _iter_modules(_PACK_PKG):
        pack = getattr(module, "PACK", None)
        if isinstance(pack, Pack):
            found[pack.name] = pack
    return found


@lru_cache(maxsize=1)
def scenes() -> dict[str, Scene]:
    found: dict[str, Scene] = {}
    for module in _iter_modules(_SCENE_PKG):
        scene = getattr(module, "SCENE", None)
        if isinstance(scene, Scene):
            found[scene.id] = scene
    return found


def scene_or_404(scene_id: str) -> Scene:
    scene = scenes().get(scene_id)
    if scene is None:
        raise KeyError(scene_id)
    return scene


def tools_of(scene: Scene):
    """场景声明了哪些包 → 展开成工具列表（**白名单**，别的包里的工具一律不给）。"""
    available = packs()
    out = []
    for name in scene.packs:
        pack = available.get(name)
        if pack is None:
            continue
        out.extend(pack.tools)
    return out


def reset_cache() -> None:
    """测试用：改了 packs/scenes 之后重新发现。"""
    packs.cache_clear()
    scenes.cache_clear()
