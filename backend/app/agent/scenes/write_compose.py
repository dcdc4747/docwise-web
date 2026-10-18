"""✍️ 写作场景：与助手一起改稿。

它和「读懂」共用同一套引擎（`runtime.py` 一行不改），差别只在：

- **pack**：多了 `writing`（列草稿 / 读草稿 / 查素材），保留 `library`（跨文献找依据）；
- **system_prompt**：不代写整篇，只做"改写 / 补依据 / 查一致性"；
- **scope**：带上 `draft_id`，工具默认读正在编辑的那一篇。

⚠️ 学术诚信边界（写在 prompt 里，也写在这里）：
**产出的是建议与依据，不是可直接提交的正文**。
"""

from __future__ import annotations

from ..contracts import Scene
from ..outputs import WriteAnswer

SYSTEM = (
    "你是写作助手，帮用户改自己的稿子。规则："
    "① 不代写整篇、不生成可直接提交的正文，只给**具体到句**的修改建议与依据；"
    "② 需要依据时先查（read_draft / search_materials / search_library），"
    "引用必须带 block_id 或 material_id；"
    "③ 指出问题要说清「哪一句、为什么、怎么改」；"
    "④ 拿不准就说不确定，不要编造文献结论；"
    "⑤ 若 read_draft 返回 empty=true，就直说「这篇草稿还没有正文」，"
    "并请用户先写一段或贴一段，不要说自己看不到稿件；"
    "⑥ 要给改写建议就放进 revisions：original 必须逐字复制稿子里的一句话"
    "（改了标点也算对不上，会被服务端剔掉），"
    "revised 是替换后的写法，reason 一句话说明。"
)


def build_context(ctx) -> str:
    """把「正在写哪一篇」带给模型；没有 draft_id 就让它自己调 list_drafts。"""
    draft_id = (ctx.scope or {}).get("draft_id")
    if not draft_id:
        return ""
    return f"用户正在编辑草稿 draft_id={draft_id}（可用 read_draft 读取）。"


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

    kept = []
    dropped = 0
    for item in revisions:
        original = (getattr(item, "original", "") or "").strip()
        # 空 original 不能用于定位，直接丢
        if original and original in body:
            kept.append(item)
        else:
            dropped += 1

    output.revisions = kept
    notes = [f"剔掉 {dropped} 条对不上原文的建议"] if dropped else []
    return output, notes


SCENE = Scene(
    id="write_compose",
    title="写作 · 与助手一起改稿",
    system_prompt=SYSTEM,
    output_type=WriteAnswer,
    packs=("writing", "library", "terms", "cite"),
    default_tier="standard",
    build_context=build_context,
    verify=verify_revisions,
    status="ready",
)
