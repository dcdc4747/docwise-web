"""Agent 层（框架无关的插件层）。

- `contracts.py`  我们的 ABI（工具 / 场景 / 上下文）
- `registry.py`   自动发现 packs 与 scenes
- `runtime.py`    **唯一 import pydantic_ai 的文件**
- `packs/`        工具包：一个功能一个文件
- `scenes/`       场景：一个入口一个文件
- `config_store.py` 每用户模型配置（密钥加密存、只写不读）
"""
