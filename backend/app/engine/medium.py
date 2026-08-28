from __future__ import annotations

from .open_source import OpenSourceEngine


class MediumEngine(OpenSourceEngine):
    """中档引擎适配器，对应中档位。

    与快档同走"子进程调包装脚本、产出 mono/dual PDF、写 result.json"的接入
    方式；部署时通过 DOCWISE_ENGINE_PYTHON / DOCWISE_ENGINE_SCRIPT /
    DOCWISE_ENGINE_SERVICE 指向中档引擎的克隆与包装脚本。
    """

    name = "medium-engine"
