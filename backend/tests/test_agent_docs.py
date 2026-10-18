"""文档 ↔ 代码一致性：工具箱清单里写的工具，必须和注册表完全一致。

为什么要有：这份清单是给用户/答辩看的"能力边界"。
一旦代码加了工具而文档没更新（或反过来），清单就开始骗人。
人工核对迟早会漏，所以把它变成用例。

⚠️ 解析只认**工具箱那张表**（表头含「包（pack）」）：
文档后面还有「场景挂载原则」表，第 3 列是**包名**而不是工具名，
不区分表格就会把包名当成工具名（第一版就错在这）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DOC = Path("../docs/agent工具箱_20261018.md")
_TOOLBOX_HEADER = "包（pack）"


def _toolbox_tool_names() -> set[str]:
    """只从"工具箱"那张表里抓工具名。"""
    if not DOC.exists():
        pytest.skip("工具箱文档不在预期位置")
    lines = DOC.read_text(encoding="utf-8").splitlines()

    names: set[str] = set()
    in_table = False
    for line in lines:
        if not line.startswith("|"):
            in_table = False
            continue
        if _TOOLBOX_HEADER in line:
            in_table = True
            continue
        if not in_table:
            continue
        cells = line.split("|")
        if len(cells) < 4:
            continue
        # cells[1]=包名, cells[2]=工具名（反引号包着）
        for name in re.findall(r"`([a-z][a-z0-9_]*)`", cells[2]):
            names.add(name)
    return names


def _registered_tools() -> set[str]:
    from app.agent import registry

    return {spec.name for pack in registry.packs().values() for spec in pack.tools}


def test_every_registered_tool_is_documented() -> None:
    missing_in_doc = _registered_tools() - _toolbox_tool_names()
    assert not missing_in_doc, f"这些工具没写进文档：{sorted(missing_in_doc)}"


def test_document_does_not_promise_missing_tools() -> None:
    phantom = _toolbox_tool_names() - _registered_tools()
    assert not phantom, f"文档承诺了但代码里没有：{sorted(phantom)}"


def test_scene_tool_counts_stay_within_budget() -> None:
    """场景工具数上限 15：超了就该拆场景（模型选工具准确率会掉）。"""
    from app.agent import registry

    for scene in registry.scenes().values():
        tools = registry.tools_of(scene)
        assert len(tools) <= 15, (
            f"{scene.id} 有 {len(tools)} 个工具，超过上限 15；该拆场景了"
        )
