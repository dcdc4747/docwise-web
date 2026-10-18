"""读懂侧场景：对话框里问文献 / 问知识库。

⭐ 这个文件就是"加一个入口"的样板：加写作助手时，照着建 `write_compose.py`，
`runtime.py` 一行都不用改。
"""

from __future__ import annotations

from ..contracts import Scene, ToolContext
from ..outputs import AskAnswer

_SYSTEM = """你是「读懂」页里的文献助手，服务对象是正在读论文的学生/研究者。

你能做的事（通过工具，不要凭空说）：
- 在用户自己的知识库里检索段落（search_library）：可以跨多篇文献；
- 读某篇文献的指定段落（read_blocks）。

硬规则：
1. 回答必须基于工具返回的内容。**不许编造文献、页码、段落编号**；
2. 引用出处时用工具返回的 block_id（例如 p0_b4），放进 source_block_ids；
3. 工具没查到就直说"库里没找到"，不要用常识替代原文；
4. 中文回答，简洁；不要复述整段原文，给出要点 + 出处。
"""


def _context(ctx: ToolContext) -> str:
    """场景自己决定带哪些上下文（这里只带"用户现在在看哪篇"）。"""
    task_id = ctx.scope.get("task_id")
    if not task_id:
        return "用户当前没有指定某一篇文献（可以跨库检索）。"
    return f"用户当前正在读 task_id={task_id} 这篇；回答可以跨库，但要优先照顾这一篇。"


SCENE = Scene(
    id="read_ask",
    title="读懂 · 问这篇文献",
    system_prompt=_SYSTEM,
    output_type=AskAnswer,
    packs=(
        "library",
        "terms",
        "tasks",
        "translate",
        "memory",
        "outline",
        "compare",
        "figures",
    ),
    default_tier="standard",
    build_context=_context,
    status="ready",
)
