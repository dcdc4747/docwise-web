"""磁盘清理（本地运维）：回收孤儿产物，默认只报告不动手。

用法（在 backend/ 目录下）：

    uv run python scripts/cleanup_data.py            # 干跑：只列出会删什么
    uv run python scripts/cleanup_data.py --yes      # 真删

清理三类东西（都只动"不属于任何任务"的文件）：

1. `data/outputs/*`：任务已删、目录还在的孤儿结果目录；
2. 系统临时目录里陈旧的引擎产物（`docwise_engine_*`）；
3. `data/uploads/*`：数据库里任何任务都不再引用的上传原件。

注意：任务还在（哪怕失败/已取消）就绝不动它的文件——用户可能正要下载或重试。
服务启动时也会自动回收第 1、2 类；本脚本用于"想立刻清一次 / 上传目录攒太多"时。
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app import storage  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Task  # noqa: E402

TEMP_AGE_SECONDS = storage.ENGINE_TEMP_MAX_AGE_SECONDS


def _known_tasks() -> tuple[set[int], set[str]]:
    with SessionLocal() as session:
        rows = session.execute(select(Task.id, Task.original_path)).all()
    ids = {row[0] for row in rows}
    uploads = {str(Path(row[1]).resolve()) for row in rows if row[1]}
    return ids, uploads


def _orphan_outputs(known_ids: set[int]) -> list[Path]:
    if not storage.OUTPUTS_DIR.exists():
        return []
    out = []
    for entry in storage.OUTPUTS_DIR.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.isdigit() and int(entry.name) in known_ids:
            continue
        out.append(entry)
    return out


def _orphan_uploads(known_uploads: set[str]) -> list[Path]:
    if not storage.UPLOADS_DIR.exists():
        return []
    out = []
    for entry in storage.UPLOADS_DIR.iterdir():
        if not entry.is_file():
            continue
        if str(entry.resolve()) in known_uploads:
            continue
        out.append(entry)
    return out


def _stale_engine_temp() -> list[Path]:
    root = Path(tempfile.gettempdir())
    cutoff = time.time() - TEMP_AGE_SECONDS
    out = []
    try:
        candidates = list(root.glob(f"{storage.ENGINE_TEMP_PREFIX}*"))
    except OSError:
        return []
    for entry in candidates:
        try:
            if entry.is_dir() and entry.stat().st_mtime <= cutoff:
                out.append(entry)
        except OSError:
            continue
    return out


def _size(paths: list[Path]) -> float:
    total = 0
    for path in paths:
        if path.is_file():
            total += path.stat().st_size
        else:
            total += sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return total / 1024 / 1024


def main() -> int:
    parser = argparse.ArgumentParser(description="docwise 磁盘清理（默认干跑）")
    parser.add_argument("--yes", action="store_true", help="确认删除（不加则只列清单）")
    args = parser.parse_args()

    known_ids, known_uploads = _known_tasks()
    outputs = _orphan_outputs(known_ids)
    uploads = _orphan_uploads(known_uploads)
    temps = _stale_engine_temp()

    print(f"任务数：{len(known_ids)}（这些任务的产物一律不动）")
    for title, paths in (
        ("孤儿结果目录", outputs),
        ("无人引用的上传原件", uploads),
        ("陈旧引擎临时目录", temps),
    ):
        size = _size(paths) if paths else 0.0
        print(f"\n{title}：{len(paths)} 项，约 {size:.2f} MB")
        for path in paths[:20]:
            print(f"  {path}")
        if len(paths) > 20:
            print(f"  …另有 {len(paths) - 20} 项")

    if not (outputs or uploads or temps):
        print("\n没有可清理的东西。")
        return 0
    if not args.yes:
        print("\n这是干跑。确认无误后加 --yes 再执行。")
        return 0

    removed = 0
    for path in outputs + uploads + temps:
        try:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
            removed += 1
        except OSError as exc:  # noqa: PERF203
            print(f"  删除失败：{path}（{exc}）")
    print(f"\n已删除 {removed} 项。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
