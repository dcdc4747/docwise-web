"""✍️ 写作场景：和助手一起写这篇稿子。

它和「读懂」共用同一套引擎（`runtime.py` 一行不改），差别只在：

- **pack**：`writing`（列草稿 / 读草稿）+ `library`（跨文献找依据）+ 术语 / 引文 /
  校对 / 排版 / 素材 / 记忆写入；
- **system_prompt**：**可以直接写正文**（用户 2026-10-19 明确取消"不代写"红线）；
- **scope**：带上 `draft_id`，工具默认读正在编辑的那一篇。

产出有两条通道：
- `ops`：**直接写进正文**（`append` / `prepend` / `replace` / `insert_after`），
  前端立即落进稿子，
  并给用户一次撤销机会；
- `revisions`：逐句的改写建议——用户点「采用」才落地（适合"这句怎么改更好"）。

⚠️ 仍有两条硬约束（不是诚信，是**别把稿子写坏**）：
① 需要锚点的操作，锚点必须逐字来自稿子，否则服务端丢掉这条；
② 引用必须带真实 block_id，编的出处会被剔掉。
"""

from __future__ import annotations

from ..contracts import Scene
from ..outputs import WriteAnswer

SYSTEM = (
    '你是用户的中文写作助手。用户让你写，你就直接写进正文；不要先问主题、体裁、摘要、'
    '关键词、参考文献，也不要把“素材不足/体例没定/不知道写哪篇”当停笔理由。\n\n硬规则：'
    '\n1. 用户说“写/先写/别管/测试/全自动/直接写”时，必须在本轮调用 writing 工具，把真'
    '实正文写进 ops。不得只回复建议、大纲、占位符、“你先确认”或“你告诉我主题”。\n2. 草'
    '稿为空也能写：根据用户最后一句话、当前标题和知识库里最近相关的文献，自行确定一个'
    '合理题目与结构，先写 600–1200 字真实内容；没有文献就写通用知识，不编造具体文献编'
    '号。\n3. 不写“【待补】”“待确认”“你需要先……”这类占位；公式或出处不确定时用自然语言'
    '写清楚，正文照常成段，不要停下来问。\n4. 用户说“测试/别管/先写”时，最多调用 1 次'
    '工具，直接 append；不要为了写作连续检索。\n5. 摘要、关键词、中图分类号、参考文献'
    '可以最后补；不要因为它们缺失而停笔或反问。\n6. 只有用户明确问“怎么写/给建议/帮我'
    '看看”时才只回答不写；其他情况默认直接写。\n7. 回复只报告“写了什么、放在哪里、下一'
    '步可改什么”，不要再问“要不要继续/先写哪节”。\n8. 如果写的是勾股定理、算法、综述等'
    '任意题目，也按上述规则直接落正文，不要要求用户先给材料。'
)


def build_context(ctx) -> str:
    """把「正在写哪一篇」和「有哪些技能」带给模型。

    ⚠️ 技能只给**索引**（名字 + 一句话何时用），正文要模型自己调 `use_skill` 取——
    这就是"渐进披露"：预装 10 个技能也不会把默认上下文撑大。
    """
    from ..skills import skill_index_prompt

    parts: list[str] = []
    draft_id = (ctx.scope or {}).get("draft_id")
    if draft_id:
        parts.append(f"用户正在编辑草稿 draft_id={draft_id}（可用 read_draft 读取）。")
    index = skill_index_prompt("write_compose")
    if index:
        parts.append(index)
    return "\n\n".join(parts)


def verify_writes(ctx, output):
    """校验 `ops`（直接写正文的操作）：锚点必须逐字在稿子里。

    返回 (输出, notes)。规则：
    - `append` / `prepend`：不需要锚点，永远放行；
    - `replace` / `insert_after`：`anchor` 必须逐字出现在正文里（换行归一后比对），
      对不上就丢掉——编一个锚点出来，用户点一下稿子就乱了；
    - 空 `text` 的操作用处不大，直接丢。
    """
    ops = list(getattr(output, "ops", []) or [])
    if not ops:
        return output, []

    draft_id = (ctx.scope or {}).get("draft_id")
    if not draft_id:
        return output, ["没有关联草稿，写入操作未执行"]

    from ...db import SessionLocal
    from ...models import Draft

    with SessionLocal() as session:
        draft = session.get(Draft, int(draft_id))
        body = (draft.body_md or "") if draft else ""

    normalized_body = body.replace("\r\n", "\n").replace("\r", "\n")
    kept = []
    dropped = 0
    for op in ops:
        mode = str(getattr(op, "mode", "") or "").strip()
        text = str(getattr(op, "text", "") or "")
        anchor = str(getattr(op, "anchor", "") or "").strip()
        if mode not in {"append", "prepend", "replace", "insert_after"}:
            dropped += 1
            continue
        if not text.strip():
            dropped += 1
            continue
        if mode in {"replace", "insert_after"}:
            normalized_anchor = anchor.replace("\r\n", "\n").replace("\r", "\n")
            if not normalized_anchor or normalized_anchor not in normalized_body:
                dropped += 1
                continue
        kept.append(op)

    output.ops = kept
    notes = [f"剔掉 {dropped} 条写不进去的操作（锚点对不上）"] if dropped else []
    return output, notes


def verify_revisions(ctx, output):
    """剔除 `original` 在稿子里找不到的建议（逐字比对）。

    返回 (输出, 剔掉说明)。没有草稿上下文时**原样放行**——
    不能因为读不到稿子就把模型说的全丢掉（那是另一种撒谎）。
    """
    revisions = list(getattr(output, "revisions", []) or [])
    if not revisions:
        return output, []

    draft_id = (ctx.scope or {}).get("draft_id")
    if not draft_id:
        # 没有指定草稿：建议保留，但明确告诉用户"没法核对原文"
        return output, ["没有关联草稿，建议未核对原文"]

    from ...db import SessionLocal
    from ...models import Draft

    with SessionLocal() as session:
        draft = session.get(Draft, int(draft_id))
        body = (draft.body_md or "") if draft else ""

    if not body.strip():
        return output, ["草稿正文为空，改写建议未核对原文"]

    # 换行归一：草稿常是 \r\n，模型给的是 \n；不归一就会"假失败"
    normalized_body = body.replace("\r\n", "\n").replace("\r", "\n")

    kept = []
    dropped = 0
    for item in revisions:
        original = (getattr(item, "original", "") or "").strip()
        normalized_original = original.replace("\r\n", "\n").replace("\r", "\n")
        # 空 original 不能用于定位，直接丢
        if normalized_original and normalized_original in normalized_body:
            kept.append(item)
        else:
            dropped += 1

    output.revisions = kept
    notes = [f"剔掉 {dropped} 条对不上原文的建议"] if dropped else []
    return output, notes


def verify_all(ctx, output):
    """两个校验一起跑：先剔掉对不上原文的建议，再剔掉锚点不对的写入操作。"""
    output, notes = verify_revisions(ctx, output)
    output, more = verify_writes(ctx, output)
    return output, notes + more


SCENE = Scene(
    id="write_compose",
    title="写作 · 和助手一起写这篇",
    system_prompt=SYSTEM,
    output_type=WriteAnswer,
    packs=(
        "writing",
        "library",
        "terms",
        "cite",
        "check",
        "biblio",
        "materials",
        # 偏好写入交给界面（设置里有入口）；把名额留给「改版式」
        # 板块专属知识（体例 / 排版 / 改稿协议），按需加载
        "skills",
        # 改版式（字号/字体/行距/缩进/套体例）：服务端改 body_html + 存一版
        "format",
    ),
    default_tier="standard",
    build_context=build_context,
    verify=verify_all,
    status="ready",
)
