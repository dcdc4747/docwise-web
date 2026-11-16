"""仓库内置引擎的位置解析。

引擎（排版翻译 + 版面模型 + 参考文献渲染）现在随仓库走，目录是 `<仓库根>/engine/`。
这里只做"路径怎么找"，不判断配置对不对——调用方拿到 None 时自己给出可执行的提示。
"""

from __future__ import annotations

from pathlib import Path

# app/engine/paths.py → parents: [engine, app, backend, <仓库根>]
ENGINE_DIR = Path(__file__).resolve().parents[3] / "engine"

FAST_SCRIPT = ENGINE_DIR / "run_translation.py"
MEDIUM_SCRIPT = ENGINE_DIR / "run_translation_medium.py"
BIBLIOGRAPHY_SCRIPT = ENGINE_DIR / "run_bibliography.py"

# 引擎自己的虚拟环境（与后端依赖树分开）：Windows 与 POSIX 两种布局都认
_VENV_PYTHONS = (".venv/Scripts/python.exe", ".venv/bin/python")


def engine_python() -> str | None:
    """引擎虚拟环境里的解释器；没装好就返回 None。"""
    for rel in _VENV_PYTHONS:
        path = ENGINE_DIR / rel
        if path.exists():
            return str(path)
    return None


def missing_parts() -> list[str]:
    """列出"还没准备好"的部分，用于把失败原因说具体。"""
    missing: list[str] = []
    if engine_python() is None:
        missing.append("engine/.venv（引擎虚拟环境）")
    required = (("run_translation.py", FAST_SCRIPT), ("csl/", ENGINE_DIR / "csl"))
    for label, path in required:
        if not path.exists():
            missing.append(f"engine/{label}")
    return missing
