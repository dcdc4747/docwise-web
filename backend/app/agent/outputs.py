"""结构化输出（场景用）。pydantic 模型，**不依赖框架**。

`source_block_ids` 仍由后端校验（框架不管这事）：模型编出来的块号一律剔掉。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AskAnswer(BaseModel):
    """读懂侧问答的收尾输出。"""

    answer: str = Field(description="给用户看的回答（中文）")
    source_block_ids: list[str] = Field(
        default_factory=list,
        description="支撑这段回答的段落编号（必须来自工具结果，不许编）",
    )
