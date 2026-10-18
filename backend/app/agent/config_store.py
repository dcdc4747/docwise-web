"""每用户模型配置的读写（密钥**只写不读**）。

优先级（方案 §八）：**请求里带的 > 用户已存 > 服务端默认（.env）**。
本模块只负责"用户已存"这一层；解析优先级在 `resolver` 里。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import UserLLMConfig
from . import crypto

# 预设：前端可以直接列出来（`base_url` 是 OpenAI 兼容端点）
PROVIDERS: list[dict] = [
    {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com/v1"},
    {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1"},
    {
        "id": "qwen",
        "name": "通义千问（DashScope 兼容）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    {
        "id": "moonshot",
        "name": "Kimi（Moonshot）",
        "base_url": "https://api.moonshot.cn/v1",
    },
    {
        "id": "zhipu",
        "name": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
    },
    {
        "id": "local",
        "name": "本地（Ollama / vLLM）",
        "base_url": "http://127.0.0.1:11434/v1",
    },
]

# 档位 → 各家预设模型（用户可覆盖）
TIER_MODELS: dict[str, dict[str, str]] = {
    "deepseek": {
        "fast": "deepseek-chat",
        "standard": "deepseek-chat",
        "strong": "deepseek-reasoner",
    },
    "openai": {"fast": "gpt-4o-mini", "standard": "gpt-4o", "strong": "o4-mini"},
    "qwen": {"fast": "qwen-turbo", "standard": "qwen-plus", "strong": "qwen-max"},
    "moonshot": {
        "fast": "moonshot-v1-8k",
        "standard": "moonshot-v1-32k",
        "strong": "moonshot-v1-128k",
    },
    "zhipu": {"fast": "glm-4-flash", "standard": "glm-4-plus", "strong": "glm-4-plus"},
    "openrouter": {"fast": "", "standard": "", "strong": ""},
    "local": {"fast": "", "standard": "", "strong": ""},
}


@dataclass
class ResolvedConfig:
    base_url: str
    model: str
    api_key: str
    tier: str
    source: str  # "user" / "server"



#: 允许按板块单独指定模型的场景（白名单：不认识的键一律忽略，防止存脏数据）
SCENE_IDS = ("read_ask", "write_compose")


def scene_models_of(row: UserLLMConfig | None) -> dict[str, str]:
    """把库里的 JSON 读成 `{scene_id: model}`；读坏了当空（不抛）。"""
    if row is None or not row.scene_models:
        return {}
    try:
        data = json.loads(row.scene_models)
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in data.items()
        if key in SCENE_IDS and str(value or "").strip()
    }


def scene_model(db: Session, user_id: int, scene_id: str) -> str:
    """这个板块要不要单独用某个模型（空串 = 跟随全局）。"""
    return scene_models_of(load_row(db, user_id)).get(scene_id, "")


def _secret() -> str:
    return (settings.docwise_secret or "").strip()


def load_row(db: Session, user_id: int) -> UserLLMConfig | None:
    return db.scalar(select(UserLLMConfig).where(UserLLMConfig.user_id == user_id))


def public_view(db: Session, user_id: int) -> dict:
    """给前端的配置视图：**绝不包含明文密钥**。"""
    row = load_row(db, user_id)
    default_ready = bool(settings.deepseek_api_key)
    if row is None:
        return {
            "configured": False,
            "provider": "deepseek" if default_ready else "",
            "base_url": "",
            "model": "",
            "tier": "standard",
            "key_set": False,
            "key_hint": "",
            "server_default": default_ready,
            "providers": PROVIDERS,
            "tier_models": TIER_MODELS,
            "scene_models": {},
        }
    return {
        "configured": True,
        "base_url": row.base_url,
        "model": row.model,
        "tier": row.tier,
        "key_set": bool(row.key_cipher),
        "key_hint": row.key_hint or "",
        "server_default": default_ready,
        "providers": PROVIDERS,
        "tier_models": TIER_MODELS,
        "scene_models": scene_models_of(row),
    }


def save(
    db: Session,
    user_id: int,
    *,
    base_url: str,
    model: str,
    tier: str,
    api_key: str | None,
    scene_models: dict[str, str] | None = None,
) -> UserLLMConfig:
    """写配置。`api_key` 为 None 表示**不动原密钥**（PUT 的常见误用是"不传就清空"）。"""
    row = load_row(db, user_id)
    if row is None:
        row = UserLLMConfig(user_id=user_id)
        db.add(row)
    row.base_url = (base_url or "").strip()
    row.model = (model or "").strip()
    row.tier = (tier or "standard").strip() or "standard"
    if scene_models is not None:
        clean = {
            key: str(value).strip()
            for key, value in scene_models.items()
            if key in SCENE_IDS and str(value or '').strip()
        }
        row.scene_models = json.dumps(clean, ensure_ascii=False) if clean else None
    if api_key is not None and api_key.strip():
        secret = _secret()
        if not secret:
            raise RuntimeError(
                "服务端没有配置 DOCWISE_SECRET，不能安全保存密钥；"
                "请改用「只在本次会话使用」或让管理员设置该环境变量"
            )
        row.key_cipher = crypto.encrypt(api_key.strip(), secret)
        row.key_hint = crypto.hint(api_key.strip())
    db.commit()
    db.refresh(row)
    return row


def clear(db: Session, user_id: int) -> None:
    row = load_row(db, user_id)
    if row is not None:
        db.delete(row)
        db.commit()


def resolve(db: Session, user_id: int, overrides: dict | None = None) -> ResolvedConfig:
    """解析出这次要用的配置：请求级 > 用户已存 > 服务端默认。"""
    overrides = overrides or {}
    row = load_row(db, user_id)
    secret = _secret()

    base_url = str(overrides.get("base_url") or "").strip()
    model = str(overrides.get("model") or "").strip()
    tier = str(overrides.get("tier") or "").strip()
    api_key = str(overrides.get("api_key") or "").strip()

    source = "request"
    if not base_url and row is not None:
        base_url = row.base_url
        source = "user"
    if not model and row is not None:
        model = row.model
    if not tier and row is not None:
        tier = row.tier
    if not api_key and row is not None and row.key_cipher and secret:
        api_key = crypto.decrypt(row.key_cipher, secret) or ""

    if not base_url or not api_key:
        # 回落到服务端默认（.env 里的 DEEPSEEK_*）
        default_base = settings.deepseek_base_url or "https://api.deepseek.com/v1"
        base_url = base_url or default_base
        api_key = api_key or (settings.deepseek_api_key or "")
        model = model or (settings.deepseek_model or "deepseek-chat")
        source = "server"

    return ResolvedConfig(
        base_url=base_url.rstrip("/"),
        model=model or "deepseek-chat",
        api_key=api_key,
        tier=tier or "standard",
        source=source,
    )
