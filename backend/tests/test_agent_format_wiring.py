"""防"工具改名但名单没跟着改"（format 包只有 `preview_styles` 是只读）。

判据：format 包里**会改库**的工具都必须在 `_DRAFT_MUTATING_TOOLS`；
只读工具（当前只有 `preview_styles`）必须显式列在白名单里——
这样以后新增一个"改库工具"却忘了加名单，用例会红。
"""

from app.agent import registry
from app.agent.runtime import _DRAFT_MUTATING_TOOLS

#: format 包里**只读**的工具（不需要前端重拉草稿）。新增只读工具要加到这里。
READ_ONLY_FORMAT_TOOLS = {"preview_styles"}


def test_mutating_format_tools_are_all_declared() -> None:
    packs = registry.packs()
    assert "format" in packs, "format 包没被注册（registry 自动发现失败？）"
    names = {spec.name for spec in packs["format"].tools}

    missing = names - READ_ONLY_FORMAT_TOOLS - set(_DRAFT_MUTATING_TOOLS)
    assert not missing, (
        f"format 包里的 {sorted(missing)} 既不是只读、也不在 _DRAFT_MUTATING_TOOLS 里；"
        "改名或新增后要同步 runtime.py，否则前端不会重拉草稿"
    )
    # 反向：只读白名单里的工具不该出现在改库名单里（否则白拉一次）
    assert not (READ_ONLY_FORMAT_TOOLS & set(_DRAFT_MUTATING_TOOLS))


def test_format_pack_is_wired_into_write_scene() -> None:
    """写作侧必须挂上 format，否则"AI 改版式"这个能力等于没接。"""
    scene = registry.scenes()["write_compose"]
    assert "format" in scene.packs
    tools = {spec.name for spec in registry.tools_of(scene)}
    assert {"preview_styles", "apply_style"} <= tools
