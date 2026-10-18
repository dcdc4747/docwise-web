"""结构化输出（场景用）。pydantic 模型，**不依赖框架**。

`source_block_ids` 与 `revisions[].original` 都由后端/前端校验：
- 块号编出来的一律剔掉（框架不管这事）；
- 改写建议里的 `original` 必须**真在稿子里**才允许「采用」——
  模型编一句原文出来，用户点应用就会把稿子改坏。
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


class Revision(BaseModel):
    """一条改写建议：**原句 → 改后**（原句必须与稿子里的一字不差）。"""

    original: str = Field(description="稿子里原样存在的一句/一段，用于定位")
    revised: str = Field(description="替换后的写法")
    reason: str = Field(default="", description="一句话说明为什么这么改")


class WriteAnswer(BaseModel):
    """写作侧的输出：除了回答，还可以带「可采用的替换建议」。"""

    answer: str = Field(description="给用户看的回答（中文）")
    source_block_ids: list[str] = Field(
        default_factory=list,
        description="支撑这段回答的段落编号（必须来自工具结果，不许编）",
    )
    revisions: list[Revision] = Field(
        default_factory=list,
        description="可选：具体到句的改写建议；original 必须原样来自稿子",
    )
