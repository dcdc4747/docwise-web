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
    "你是这位用户的写作助手，和他一起把这篇稿子写出来。**可以直接往正文里写**"
    "（用户已授权；写进去之后他会自己再改）。规则："
    "① 需要落笔就直接写进 ops，不要只在回答里给文字让他复制；"
    "写整节用 insert_after（锚点=该节标题原文），重写某节用 replace（锚点=原文），"
    "写结论/新章节用 append，写标题/摘要用 prepend；"
    "② ops 里的锚点（anchor）必须**逐字复制**稿子里已有的文字，"
    "改了标点或跨了不相邻的段都会对不上而被服务端剔掉；"
    "③ 要依据就先查（read_draft / search_materials / search_library / "
    "list_figures / run_check），引用必须带真实 block_id 或 material_id；"
    "④ 指出问题要说清「哪一句、为什么、怎么改」；"
    "⑤ 拿不准就说不确定，不要编造文献结论；"
    "⑥ 若 read_draft 返回 empty=true，这篇还没有正文——**可以直接写**："
    "先用 append 写一节，或按模板骨架写；不要说自己看不到稿件；"
    "⑦ 只想给「改法」而不动稿子时，用 revisions：original 必须逐字复制原文，"
    "可以是**一句**，也可以是**一整段（多句连在一起）**；"
    "改了标点、或跨了两个不相邻的段落，都会对不上而被服务端剔掉；"
    "revised 是替换后的写法（与 original 同样可以是整段），reason 一句话说明。"
)


def build_context(ctx) -> str:
    """把「正在写哪一篇」带给模型；没有 draft_id 就让它自己调 list_drafts。"""
    draft_id = (ctx.scope or {}).get("draft_id")
    if not draft_id:
        return ""
    return f"用户正在编辑草稿 draft_id={draft_id}（可用 read_draft 读取）。"


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
        "memory_write",
    ),
    default_tier="standard",
    build_context=build_context,
    verify=verify_all,
    status="ready",
)
