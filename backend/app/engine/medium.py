from __future__ import annotations

from .open_source import OpenSourceEngine


class MediumEngine(OpenSourceEngine):
    """中档引擎适配器，对应中档位。

    与快档同走"子进程调包装脚本、产出 mono/dual PDF、写 result.json"的接入
    方式；部署时通过 DOCWISE_ENGINE_MEDIUM_PYTHON / DOCWISE_ENGINE_MEDIUM_SCRIPT /
    DOCWISE_ENGINE_MEDIUM_SERVICE 指向中档引擎的克隆与包装脚本（未配则回退到基础的
    DOCWISE_ENGINE_*）。这样快、中档可用不同引擎，也便于按档位切换。
    """

    name = "medium-engine"
    # 中档专属环境变量：DOCWISE_ENGINE_MEDIUM_PYTHON/SCRIPT/SERVICE，未配则回退基础变量
    env_prefix = "DOCWISE_ENGINE_MEDIUM"
