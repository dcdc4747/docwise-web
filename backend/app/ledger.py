"""环节台账（M2 写 / M5 读 / M7 吃）——**全仓唯一的写入入口**。

为什么要有这个模块：`memory_events` 是"AI 使用台账"与"处理过程一屏"的**唯一真源**
（契约 §2.5：N17 与 N26 **同源**，不许做两份台账）。如果让每个环节各自
`MemoryEvent(...)` 散写，迟早出现"改一处漏三处"——所以写入**只有这一个函数**。

三条硬口径：

1. ⭐ **写入失败绝不影响主流程**：台账是"记录"，不是"业务"。本模块**自己开一个会话、
   自己 commit**，与调用方的事务完全隔离——调用方不会因为台账写失败而回滚，
   也不会被台账的写锁拖住（这也是为什么它不接调用方传进来的 `Session`）。
2. ⭐ **只记真实发生的事**：必填字段为空就**跳过并记日志**，不写半条；
   没跑的步骤不写事件；
   失败的步骤**如实写成失败**，不许记成成功。
3. `actor` 是"数据流向"的证据（见 `MemoryEvent` 的模型文档）：取字与扫描件
   OCR 是**真本地**
   → `local`；外文翻译 / 导读 / 问答三条路发往云端模型 API → `api`。⚠️ 对外口径仍然是
   「**服务自持 + 文献存本地**」，**不能讲"数据不出本机"**。

⚠️ **问答没有单独的表**：本次实测确认 `sqlite_master` 里**没有 `ask_logs`**，契约也没要求
另建一张；而 §2.5 明确"台账只有一份"。所以问答落库就是**一条 `stage="ask"` 的台账**，
`payload` 里带问题 / 回答 / 出处——`/api/ask-logs`（N15/N16）读的也是它，
**不新建表、不写迁移**。
"""

from __future__ import annotations

import logging
from typing import Any

from .db import SessionLocal
from .models import MemoryEvent
from .routers.me import _memory_event_view
from .timeutil import iso_utc

logger = logging.getLogger(__name__)

# 与模型里的列宽对齐（超了就截断，**不是**报错——台账不该因为一句话太长而丢事件）
_LAYER_MAX = 8
_STAGE_MAX = 32
_ACTOR_MAX = 16
_TOOL_MAX = 64
_SUMMARY_MAX = 500

# 问答：一条台账最多带多少条出处（超了只影响 payload 体积，不影响主流程）
_ASK_SOURCES_MAX = 200


def record_event(
    *,
    user_id: int,
    stage: str,
    actor: str,
    summary: str,
    task_id: int | None = None,
    layer: str = "L0",
    tool: str | None = None,
    payload: dict[str, Any] | None = None,
) -> int | None:
    """写一条台账，返回它的 id；**任何失败都只记日志 + 返回 None**。

    调用方**不需要**判返回值：台账写不进去，主流程照常（这是本模块存在的意义）。
    只有 `/api/memory-events`、`/api/ask-logs` 这两个"目的就是写"的接口才会去看它，
    那两处拿不到 id 会如实回 503（不给"写了"的假象）。
    """
    if not user_id or not stage or not actor or not summary:
        # 缺必填字段：**跳过并记日志**，绝不写半条（半条比没有更糟：界面会显示它）
        logger.warning(
            "台账事件字段不全，已跳过：user_id=%s stage=%r actor=%r",
            user_id,
            stage,
            actor,
        )
        return None

    try:
        with SessionLocal() as session:
            row = MemoryEvent(
                user_id=int(user_id),
                task_id=task_id,
                layer=str(layer)[:_LAYER_MAX],
                stage=str(stage)[:_STAGE_MAX],
                actor=str(actor)[:_ACTOR_MAX],
                tool=str(tool)[:_TOOL_MAX] if tool else None,
                summary=str(summary)[:_SUMMARY_MAX],
                payload=payload,
            )
            session.add(row)
            session.commit()
            return row.id
    except Exception:  # noqa: BLE001 - 台账写失败绝不能影响主流程
        logger.exception(
            "写台账失败（已忽略，不影响主流程）：stage=%s task_id=%s", stage, task_id
        )
        return None


def record_ask(
    *,
    user_id: int,
    question: str,
    answer: str,
    source_block_ids: list[str],
    task_id: int | None = None,
    called_model: bool = True,
) -> int | None:
    """问答落库（N15 的**服务端**写入路径）：一条 `stage="ask"` 的台账。

    `summary` 给台账界面看（人话一行）；`payload` 带**原始问答与出处**，
    给 N16 读回、也给"逐条下钻"用。

    ⚠️ `called_model` 决定 `actor`/`tool`：全文与检索两条路**真的调了模型**（`api`），
    而检索没召回时**一次模型都没调**（`local`）——台账上这两件事**不能长一个样**，
    否则"哪些步骤把内容发出去了"这条证据就失真了。
    """
    ids = [str(item) for item in (source_block_ids or [])][:_ASK_SOURCES_MAX]
    head = (question or "").strip().replace("\n", " ")
    if called_model:
        summary = f"回答提问：{head[:60]}｜出处 {len(ids)} 条"
    else:
        summary = f"检索没命中，未调用模型：{head[:60]}"
    return record_event(
        user_id=user_id,
        task_id=task_id,
        stage="ask",
        actor="api" if called_model else "local",
        tool="model-api" if called_model else "fts",
        summary=summary,
        payload={
            "question": question,
            "answer": answer,
            "source_block_ids": ids,
            "called_model": called_model,
        },
    )


def ask_log_view(row: MemoryEvent) -> dict:
    """问答台账一行（`/api/ask-logs` 的形状，与前端契约 mock 逐字段对齐）。"""
    payload = row.payload if isinstance(row.payload, dict) else {}
    sources = payload.get("source_block_ids")
    return {
        "id": row.id,
        "task_id": row.task_id,
        "question": str(payload.get("question") or ""),
        "answer": str(payload.get("answer") or ""),
        "source_block_ids": (
            [str(item) for item in sources] if isinstance(sources, list) else []
        ),
        "created_at": iso_utc(row.created_at),
    }


def ask_logs(
    rows: list[MemoryEvent],
) -> list[dict]:
    """把一批台账行里**属于问答的那些**挑出来并转成 N16 的形状。"""
    return [ask_log_view(row) for row in rows if row.stage == "ask"]


def event_view(row: MemoryEvent) -> dict:
    """台账一行（N17 与 N26 **共用**这个形状，别写第二份）。"""
    return _memory_event_view(row)
