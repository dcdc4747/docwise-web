"""磁盘治理：上传文件与结果文件的唯一约定。

约定（E 批定稿）：

- 上传原件：`data/uploads/{uuid}_{原文件名}`
- 结果目录：`data/outputs/{task_id}/`（引擎的 mono/dual PDF、result.json、engine.log
  全在这里）——**按任务一个目录**，删除任务时整体删掉，不存在"漏删的散落文件"。
- 清理口径：删除任务 / 重试任务时删掉对应文件；启动时回收孤儿目录
  （不属于任何任务的 `data/outputs/*`）与陈旧的引擎临时目录。

模块级变量（而不是常量）是为了让测试能整体改到临时目录：
测试里 `app.storage.UPLOADS_DIR = ...` 即可，不要 `from .storage import UPLOADS_DIR`
那样会把值冻住。
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from pathlib import Path

from .config import BASE_DIR

logger = logging.getLogger(__name__)

DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
OUTPUTS_DIR = DATA_DIR / "outputs"
BACKUPS_DIR = DATA_DIR / "backups"

# 引擎自己开的临时目录前缀（老版本用它，新版本改用 outputs/{task_id}）
ENGINE_TEMP_PREFIX = "docwise_engine_"
# 启动时清理超过这个岁数的引擎临时目录（秒）
ENGINE_TEMP_MAX_AGE_SECONDS = 24 * 3600


def uploads_dir() -> Path:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOADS_DIR


def outputs_dir(task_id: int) -> Path:
    """某个任务的结果目录（`data/outputs/{task_id}`）。"""
    path = OUTPUTS_DIR / str(task_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_within(path: Path, root: Path) -> bool:
    """path 是否在 root 目录之内（防"记录里的路径被人改过，删到系统文件"）。"""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def remove_file(path: Path | None) -> bool:
    """删单个文件，只删得掉"我们自己的地盘"里的文件。

    允许的范围：`data/` 之内，或系统临时目录里 `docwise_engine_*`（老版本引擎产物）。
    返回是否真的删掉了。
    """
    if path is None:
        return False
    try:
        if not path.exists() or not path.is_file():
            return False
        allowed = is_within(path, DATA_DIR) or (
            path.parent.name.startswith(ENGINE_TEMP_PREFIX)
            and is_within(path, Path(tempfile.gettempdir()))
        )
        if not allowed:
            logger.warning("拒绝删除 data 目录之外的文件：%s", path)
            return False
        path.unlink()
        return True
    except OSError:
        logger.exception("删除文件失败：%s", path)
        return False


def remove_dir(path: Path) -> bool:
    """删整个目录（仅限 data/ 之内）。"""
    try:
        if not path.exists() or not path.is_dir():
            return False
        if not is_within(path, DATA_DIR):
            logger.warning("拒绝删除 data 目录之外的目录：%s", path)
            return False
        shutil.rmtree(path, ignore_errors=True)
        return True
    except OSError:
        logger.exception("删除目录失败：%s", path)
        return False


def remove_task_files(
    task_id: int,
    original_path: str | None = None,
    translated_path: str | None = None,
    dual_path: str | None = None,
) -> None:
    """删除一个任务的所有磁盘产物（上传原件 + 结果目录 + 记录里的零散路径）。

    结果目录整体删除是主路径；记录里的路径是兜底（老任务的结果在系统临时目录里，
    当时没有按任务建目录）。
    """
    remove_dir(OUTPUTS_DIR / str(task_id))
    remove_file(Path(original_path) if original_path else None)
    remove_file(Path(translated_path) if translated_path else None)
    remove_file(Path(dual_path) if dual_path else None)


def cleanup_orphan_outputs(known_ids: set[int]) -> int:
    """回收孤儿结果目录：`data/outputs/*` 里不属于任何任务的目录。

    返回清理个数。任务还在（哪怕已失败）就绝不动它的目录——用户可能正要下载。
    """
    if not OUTPUTS_DIR.exists():
        return 0
    removed = 0
    for entry in OUTPUTS_DIR.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.isdigit() and int(entry.name) in known_ids:
            continue
        if remove_dir(entry):
            removed += 1
            logger.info("回收孤儿结果目录：%s", entry.name)
    return removed


def cleanup_engine_temp_dirs(max_age_seconds: int = ENGINE_TEMP_MAX_AGE_SECONDS) -> int:
    """清理老版本引擎留在系统临时目录里的产物（超过 max_age_seconds 才动）。"""
    removed = 0
    root = Path(tempfile.gettempdir())
    try:
        candidates = list(root.glob(f"{ENGINE_TEMP_PREFIX}*"))
    except OSError:
        return 0
    cutoff = time.time() - max_age_seconds
    for entry in candidates:
        try:
            if not entry.is_dir() or entry.stat().st_mtime > cutoff:
                continue
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
        except OSError:
            continue
    if removed:
        logger.info("清理陈旧的引擎临时目录 %s 个", removed)
    return removed
