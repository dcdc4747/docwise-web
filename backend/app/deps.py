"""集中依赖注入（2026.9.8 定稿决策⑤）。

路由统一 `Depends(get_db)` / `Depends(get_settings)`；get_db 从 db.py 再导出，
保持单一实现（旧路由暂从 db.py 直用，后续可渐进迁移到本模块）。
"""

from .config import Settings, settings
from .db import SessionLocal, get_db

__all__ = ["Settings", "SessionLocal", "get_db", "get_settings", "settings"]


def get_settings() -> Settings:
    return settings
