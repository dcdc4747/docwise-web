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


class WriteOp(BaseModel):
    """一条**写入正文**的操作（2026-10-19：取消"不代写"红线）。

    语义与前端一一对应，`anchor` 是**稿子里原样存在的一段文字**（定位用）：
    - `append`：在全文末尾追加（写新一节、写结论）
    - `prepend`：在全文最前面插入（写标题/摘要）
    - `replace`：把 `anchor` 那段换成 `text`（重写某一节）
    - `insert_after`：在 `anchor` 那段之后插入 `text`（在某节后面续写）

    ⚠️ 需要 `anchor` 的两种（`replace` / `insert_after`），锚点必须在稿子里**逐字**存在，
    否则服务端会丢掉这条——编一个锚点出来会把用户的稿子写乱。
    """

    mode: str = Field(description="append / prepend / replace / insert_after")
    text: str = Field(default="", description="要写进正文的文本（Markdown）")
    anchor: str = Field(
        default="",
        description="定位用的原文片段；replace / insert_after 必填，必须逐字来自稿子",
    )
    reason: str = Field(default="", description="一句话说明为什么这么写（给用户看的）")


class WriteAnswer(BaseModel):
    """写作侧的输出：除了回答，还可以带「可采用的替换建议」和「直接写入正文的操作」。"""

    answer: str = Field(description="给用户看的回答（中文）")
    source_block_ids: list[str] = Field(
        default_factory=list,
        description="支撑这段回答的段落编号（必须来自工具结果，不许编）",
    )
    revisions: list[Revision] = Field(
        default_factory=list,
        description="可选：具体到句的改写建议；original 必须原样来自稿子",
    )
    ops: list[WriteOp] = Field(
        default_factory=list,
        description=(
            "可选：**直接写进正文**的操作（用户已授权代写）。"
            "整节续写用 insert_after + 该节标题；重写某节用 replace；"
            "写全新内容用 append。前端会立即写入并给一次撤销机会。"
        ),
    )
