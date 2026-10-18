"""Agent 路由（N46–N50，契约 74 → 79）。

P0 先做**非流式**：一次请求把"回答 + 轨迹 + 用量"一起返回（SSE 留到 P1）。
这样前端能先把界面做出来，后端也能独立验收。

⚠️ 密钥只写不读：`GET /config` 永远不含明文。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..agent import config_store, registry, runtime
from ..deps import get_current_user, get_db
from ..models import User

router = APIRouter(prefix="/api/agent", tags=["agent"])


class ConfigIn(BaseModel):
    base_url: str = Field(default="", max_length=512)
    model: str = Field(default="", max_length=128)
    tier: str = Field(default="standard", max_length=16)
    # 不传 = 不动原密钥（PUT 的常见误用是"不传就清空"）
    api_key: str | None = Field(default=None, max_length=512)


class ChatIn(BaseModel):
    scene: str = Field(default="read_ask", max_length=64)
    question: str = Field(min_length=1, max_length=2000)
    # 页面带来的上下文，只收白名单字段（不许塞任意对象）
    scope: dict[str, Any] = Field(default_factory=dict)
    # 可选：本次请求临时用某个 key（**不落库**，给"不想存密钥"的人）
    override: dict[str, str] | None = None


_SCOPE_KEYS = {"task_id", "draft_id", "selection", "page"}


@router.get("/scenes")
def list_scenes() -> dict:
    """可用场景（前端据此渲染；加场景不用改前端）。"""
    return {
        "items": [
            {
                "id": scene.id,
                "title": scene.title,
                "status": scene.status,
                "default_tier": scene.default_tier,
                "packs": list(scene.packs),
            }
            for scene in registry.scenes().values()
        ]
    }


@router.get("/config")
def get_config(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    return config_store.public_view(db, user.id)


@router.put("/config")
def put_config(
    payload: ConfigIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    if payload.tier not in {"fast", "standard", "strong"}:
        raise HTTPException(
            status_code=400, detail="tier 只能是 fast / standard / strong"
        )
    try:
        config_store.save(
            db,
            user.id,
            base_url=payload.base_url,
            model=payload.model,
            tier=payload.tier,
            api_key=payload.api_key,
        )
    except RuntimeError as exc:
        # 没有 DOCWISE_SECRET：拒绝落库并说清楚（不偷偷用写死的常量）
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return config_store.public_view(db, user.id)


@router.delete("/config")
def delete_config(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    config_store.clear(db, user.id)
    return config_store.public_view(db, user.id)


@router.post("/chat")
async def chat(
    payload: ChatIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """跑一次场景。**先把能报的错报干净**，别让用户打完字才 500。"""
    try:
        scene = registry.scene_or_404(payload.scene)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail=f"没有这个场景：{payload.scene}"
        ) from exc
    if scene.status != "ready":
        raise HTTPException(
            status_code=400,
            detail=f"场景「{scene.title}」还没开放（status={scene.status}）",
        )

    scope = {k: v for k, v in (payload.scope or {}).items() if k in _SCOPE_KEYS}
    cfg = config_store.resolve(db, user.id, payload.override)
    if not cfg.api_key:
        raise HTTPException(
            status_code=400,
            detail=(
                "还没配模型：去 ⚙️ 填一个"
                "（或让管理员在 .env 里配 DEEPSEEK_API_KEY）"
            ),
        )

    result = await runtime.run_scene(
        scene,
        payload.question.strip(),
        user_id=user.id,
        scope=scope,
        cfg=runtime.LLMConfig(
            base_url=cfg.base_url, api_key=cfg.api_key, model=cfg.model
        ),
    )
    # 台账：记"用了哪家模型、调了几次工具"，**不记 prompt 全文、不记 key**
    try:
        from ..ledger import record_ask

        record_ask(
            user_id=user.id,
            task_id=scope.get("task_id"),
            question=payload.question.strip(),
            answer=result["answer"],
            source_ids=result["sources"],
            mode=f"agent:{scene.id}",
        )
    except Exception:  # noqa: BLE001 —— 台账失败不影响回答
        pass
    return {
        "answer": result["answer"],
        "sources": result["sources"],
        "dropped_sources": result["dropped_sources"],
        "steps": result["steps"],
        "usage": result["usage"],
        "scene": scene.id,
        "model": cfg.model,
        "config_source": cfg.source,
    }
