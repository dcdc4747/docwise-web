"""记忆写入包（`save_memory` / `save_term_preference`）。

⚠️ **实现仍在 `memory.py`**（一处实现），这里只是把它们**单独注册成一个包**：
读懂场景只要"读记忆"，写作场景才需要"写记忆"。
拆包是为了**场景工具数不超上限**（15），不是为了分家。
"""

from __future__ import annotations

from ..contracts import Pack, ToolSpec
from .memory import save_memory, save_term_preference

PACK = Pack(
    name="memory_write",
    tools=(
        ToolSpec(
            name="save_memory",
            description=(
                "把一条记忆存下来（kind=term 术语/译名偏好，kind=cite 引用习惯）。"
                "**必须 confirm=true 才真的写**；不带 confirm 只返回说明。"
                "按 (kind, source) 幂等更新，不会影响命中次数。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["term", "cite"]},
                    "source": {"type": "string", "description": "术语原词/引用场景"},
                    "target": {"type": "string", "description": "译名/偏好值"},
                    "enabled": {"type": "boolean"},
                    "confirm": {"type": "boolean", "description": "true 才真的写"},
                },
                "required": ["kind", "source", "target"],
            },
            handler=save_memory,
            max_result_chars=2000,
        ),
        ToolSpec(
            name="save_term_preference",
            description=(
                "记住一个术语的固定译名（跨会话一致）。**必须 confirm=true 才写**。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "term": {"type": "string", "description": "术语原词"},
                    "cn": {"type": "string", "description": "固定译名"},
                    "confirm": {"type": "boolean", "description": "true 才真的写"},
                },
                "required": ["term", "cn"],
            },
            handler=save_term_preference,
            max_result_chars=2000,
        ),
    ),
)
