"""参考文献格式化（契约 §2.6 的 N31）。

⚠️ **重活全在引擎侧**：CSL 样式数据是第三方（CC BY-SA 3.0）的，
**只存在于引擎目录**，
绝不复制进本仓库。本模块只做三件事：

1. **守门**：只认自己的草稿（非本人 404），样式 key 只在白名单里放行（非法 400）；
2. **原样喂**：把 `citations.csl_json` **一条不改**地交给引擎脚本
   （别在这里"顺手修" item）；
3. **原样回**：把引擎的 JSON 原样回给前端，只**追加**一个 `styles` 字段
   （支持的样式 key 清单，省得前端为画一个下拉框再去问一次引擎）。

诚实口径（与收口那套 `unknown` 一脉相承）：**引擎没配好 / 脚本不存在 / 进程起不来 /
超时 / 退出码非 0** 一律 **503 + 人话**——**不返回半成品，也不假装格式化成功**。
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db
from ..models import User
from ..netenv import sanitize_proxy_env
from .drafts import _citations_of, _load_owned_draft

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/drafts", tags=["bibliography"])

# 引擎脚本支持的样式 key（**引擎是权威**：跑
# `run_bibliography.py --list-styles` 可核对）。
# 这份清单只用于两件事：校验入参、告诉前端有哪些可选——**样式数据本身不在后端**。
SUPPORTED_STYLES: tuple[str, ...] = (
    "apa",
    "ieee",
    "gb-t-7714-2015-numeric",
    "gb-t-7714-2015-author-date",
)

# 格式化是"一次渲染"，与翻译（1800 秒）不是一个量级；超时按失败报，不无声挂着。
_TIMEOUT_SECONDS = 60


def _resolve_script() -> Path | None:
    """找格式化脚本：先看专属变量，再按 `DOCWISE_ENGINE_SCRIPT` **同目录**推。

    两处都拿不到就返回 None（接口回 503 并说清缺哪个变量），**不瞎猜路径**。
    """
    explicit = os.environ.get("DOCWISE_ENGINE_BIBLIOGRAPHY_SCRIPT")
    if explicit:
        return Path(explicit)
    sibling = os.environ.get("DOCWISE_ENGINE_SCRIPT")
    if sibling:
        return Path(sibling).parent / "run_bibliography.py"
    return None


def _unavailable(detail: str) -> HTTPException:
    """503 + 人话：环境没配好时**如实说**，绝不返回半成品。"""
    return HTTPException(status_code=503, detail=detail)


def _empty(style: str) -> dict:
    """没有引文时的**如实空表**（形状与引擎成功返回的完全一致）。"""
    return {
        "style": style,
        "locale": None,
        "entries": [],
        "item_texts": {},
        "count": 0,
        "skipped": [],
        "styles": list(SUPPORTED_STYLES),
    }


# 上传落盘名是 `{32位hex}_{原名}`（storage 那边定的），但**引用条目里不该出现哈希**。
# 素材是"创建时快照"，不会跟着文献改名，所以只能在出参这一层洗。
_STORAGE_PREFIX_RE = re.compile(r"^[0-9a-f]{32}_")


def _strip_storage_prefix(value):
    """把一个字段里的哈希前缀去掉；非字符串原样返回。"""
    if not isinstance(value, str):
        return value
    return _STORAGE_PREFIX_RE.sub("", value)


def _clean_csl(item):
    """CSL 条目的字符串字段都洗一遍（title / container-title / URL 都可能带前缀）。"""
    if not isinstance(item, dict):
        return item
    return {key: _strip_storage_prefix(value) for key, value in item.items()}


@router.get("/{draft_id}/bibliography")
def draft_bibliography(
    draft_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    style: Annotated[str, Query()] = "",
):
    """`GET /api/drafts/{id}/bibliography?style=<key>` → `200 Bibliography`。

    - 样式 key 非法（含没传）→ **400**，detail 里列出可选 key；
    - 草稿不存在 / 不是本人的 → **404**；
    - 没有引文 → **200 空表**（不白跑引擎；样式 key 仍然先校验）；
    - 引擎不可用 → **503**。
    """
    style_key = (style or "").strip()
    if style_key not in SUPPORTED_STYLES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"不支持的样式 key：{style_key or '(空)'}；"
                f"可选 {' / '.join(SUPPORTED_STYLES)}"
            ),
        )

    draft = _load_owned_draft(db, user, draft_id)
    items = [_clean_csl(row.csl_json) for row in _citations_of(db, draft.id)]
    if not items:
        return _empty(style_key)

    python = os.environ.get("DOCWISE_ENGINE_PYTHON")
    if not python:
        raise _unavailable("参考文献格式化需要引擎环境（未配置 DOCWISE_ENGINE_PYTHON）")
    script = _resolve_script()
    if script is None:
        raise _unavailable(
            "参考文献格式化需要引擎环境（未配置 "
            "DOCWISE_ENGINE_BIBLIOGRAPHY_SCRIPT，也推不出同目录的 run_bibliography.py）"
        )
    if not script.is_file():
        raise _unavailable(f"参考文献格式化脚本不存在：{script}")

    child_env = os.environ.copy()
    # Windows 下子进程默认按 GBK 读写，中文条目会被搞成孤立代理字符 →
    # 三个流都钉 UTF-8（与引擎适配器同一条防线）。
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env["PYTHONUTF8"] = "1"
    # 代理环境变量先洗一遍：`NO_PROXY` 里带方括号的 IPv6 会炸掉 httpx 的 URLPattern
    # （引擎侧踩过一次，见 app/netenv.py 的说明）。
    sanitize_proxy_env(child_env)

    try:
        proc = subprocess.run(
            [python, str(script), "--style", style_key],
            input=json.dumps({"items": items}, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=child_env,
            # 引擎侧的 `csl/` 就在脚本旁边，用它的目录当工作目录最稳
            cwd=str(script.parent),
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise _unavailable(f"参考文献格式化超时（超过 {_TIMEOUT_SECONDS} 秒）") from exc
    except OSError as exc:
        raise _unavailable(f"参考文献格式化起不来引擎进程：{exc}") from exc

    if proc.returncode != 0:
        tail = [line for line in (proc.stderr or "").strip().splitlines() if line]
        reason = " / ".join(tail[-3:]) or "引擎没有给出原因"
        raise _unavailable(
            f"参考文献格式化失败（引擎退出码 {proc.returncode}）：{reason}"
        )

    try:
        result = json.loads(proc.stdout or "")
    except json.JSONDecodeError as exc:
        raise _unavailable("参考文献格式化失败：引擎输出不是 JSON") from exc
    if not isinstance(result, dict):
        raise _unavailable("参考文献格式化失败：引擎输出的形状不对")

    # 只**追加** styles，其余字段原样透传（引擎返回什么就是什么）
    result["styles"] = list(SUPPORTED_STYLES)
    logger.info(
        "参考文献格式化：draft_id=%s style=%s items=%s",
        draft.id,
        style_key,
        len(items),
    )
    return result
