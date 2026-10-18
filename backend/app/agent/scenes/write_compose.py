"""🕳 写作场景（口子，先不实现）。

以后要开写作助手时，**只需要**：
1. 把 `packs` 换成 `("library", "writing")`，并在 `packs/writing.py` 里加工具；
2. 写好 `system_prompt` 与 `output_type`；
3. 前端某处挂一行 `<AgentPanel scene="write_compose" :scope="{ draftId }" />`。

`runtime.py` 不需要动——这就是"加一个文件就能接"的判据。
现在 `status="planned"`：`GET /api/agent/scenes` 会把它列出来（前端显示"即将开放"），
但 `POST /api/agent/chat` 会拒绝（400），免得用户点了没反应还不知道为什么。
"""

from __future__ import annotations

from ..contracts import Scene
from ..outputs import AskAnswer


def _not_ready(*_args, **_kwargs) -> str:
    return ""


SCENE = Scene(
    id="write_compose",
    title="写作 · 与助手一起写（即将开放）",
    system_prompt="（占位）写作助手：读草稿、插引文、查术语一致性。",
    output_type=AskAnswer,
    packs=(),
    default_tier="standard",
    build_context=_not_ready,
    status="planned",
)
