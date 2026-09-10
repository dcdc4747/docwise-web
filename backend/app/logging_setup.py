"""统一日志（保命基建）：落文件 + 控制台。

出问题时能翻记录，而不是只能猜——此前全仓没有一行日志。
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import BASE_DIR

LOG_DIR = BASE_DIR / "data" / "logs"
LOG_FILE = LOG_DIR / "docwise.log"
_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    """初始化根日志（幂等）：文件按 5MB 轮转、保留 3 份，同时输出到控制台。

    写不了日志文件时（只读文件系统等）自动降级为"仅控制台"，绝不因此启动失败。
    """
    global _configured
    if _configured:
        return

    formatter = logging.Formatter(_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")

    root = logging.getLogger()
    root.setLevel(level)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:  # 只读/无权限：降级为控制台日志
        root.addHandler(logging.NullHandler())

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    _configured = True
