"""Skill 层（2026-10-19）：给每个板块预装"知识 + 流程"，按需加载。

## 为什么要这一层

现在两个板块的差别只有「挂哪几个工具 + 一段 prompt」（实测：读懂 281 字、写作 630 字）。
但专业差异不只在工具，而在**这类活该怎么做**：中文期刊正文该用什么字号、
引用该放在哪、摘要四句话怎么排。把这些写进 prompt 会撑爆上下文，
写进工具又不合适（它不是"动作"）——所以单独一层 **Skill**。

## 与另外两层的分工

| 层 | 是什么 | 谁维护 |
|---|---|---|
| Tool / Pack | 可执行函数（查库、写正文、改字号） | Python |
| **Skill** | **知识 + 流程 + 判据**（Markdown） | 写手/工程师都能改 |
| MCP | 接外部系统（Zotero、Overleaf） | 外部服务 |

## 三条硬规则

1. **渐进披露**：prompt 里只放索引（每条 ≤40 字）；模型判断要用时调 `use_skill(name)` 取正文。
   这样"预装 10 个 skill"也不会把默认上下文撑大。
2. **预算封顶**：单个 skill 正文 ≤4000 字（读的时候再截断），一轮最多调用 2 次——
   防止模型把 skill 当百科翻。
3. **可验收**：skill 带 `checks` 列表（能算的判据），供 `run_check` / scene 的 `verify` 使用。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

#: skill 正文的读取上限（约 4 KB 中文），超出截断并如实说明
MAX_BODY_CHARS = 4000
#: 一轮对话里最多加载几个 skill（防"翻百科"）
MAX_PER_TURN = 2

_SKILL_ROOT = Path(__file__).with_name("skill_docs")


@dataclass(frozen=True)
class Skill:
    """一个 skill：名字 + 适用板块 + 何时用 + 正文 + 可机器校验的条目。"""

    name: str
    title: str
    applies_to: tuple[str, ...]
    when: str
    body: str = ""
    checks: tuple[dict, ...] = field(default=())

    def index_line(self) -> str:
        """进 prompt 的那一行（必须短：这是"渐进披露"的索引）。"""
        return f"- {self.name}：{self.when}"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:  # 读不到就当没有，不阻断对话
        return ""


def load_skills(root: Path | None = None) -> dict[str, Skill]:
    """扫 `skill_docs/` 目录，按 `_index.json` 里的声明组装 skill。

    ⚠️ 正文放在 `<name>/SKILL.md`，而**索引只读 `_index.json`**——
    这样"有哪些 skill"不用把每个正文都读进内存，也不用解析 Markdown 头部。
    """
    base = root or _SKILL_ROOT
    index_path = base / "_index.json"
    raw = _read_text(index_path)
    if not raw:
        return {}
    try:
        declared = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    skills: dict[str, Skill] = {}
    for item in declared.get("skills", []):
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        folder = base / name
        body = _read_text(folder / "SKILL.md").strip()
        checks_raw = _read_text(folder / "checks.json")
        checks: tuple[dict, ...] = ()
        if checks_raw:
            try:
                parsed = json.loads(checks_raw)
                if isinstance(parsed, list):
                    checks = tuple(item for item in parsed if isinstance(item, dict))
            except json.JSONDecodeError:
                checks = ()
        skills[name] = Skill(
            name=name,
            title=str(item.get("title") or name),
            applies_to=tuple(item.get("applies_to") or ()),
            when=str(item.get("when") or ""),
            body=body,
            checks=checks,
        )
    return skills


def skills_for(scene_id: str, root: Path | None = None) -> list[Skill]:
    """某个板块可用的 skill（按索引顺序，稳定）。"""
    return [
        skill
        for skill in load_skills(root).values()
        if scene_id in skill.applies_to
    ]


def skill_index_prompt(scene_id: str, root: Path | None = None) -> str:
    """给 prompt 用的索引块；没有 skill 就返回空串（别塞一段"暂无"占地方）。"""
    skills = skills_for(scene_id, root)
    if not skills:
        return ""
    lines = [skill.index_line() for skill in skills]
    return "可用技能（需要时调 use_skill 取详情）：\n" + "\n".join(lines)
