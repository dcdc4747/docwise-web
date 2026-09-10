"""数据库备份 / 恢复说明（本地运维）。

用法（在 backend/ 目录下）：

    uv run python scripts/backup_db.py   # 备份到 data/backups/，留最近 7 份
    uv run python scripts/backup_db.py --keep 14        # 保留最近 14 份
    uv run python scripts/backup_db.py --out D:\backup  # 换目标目录（如移动硬盘）
    uv run python scripts/backup_db.py --list           # 看看现有备份

为什么不用"复制文件"：SQLite 开的是 WAL 模式，最近的写入还在 `-wal` 里，
直接拷 `.db` 会**丢最近的改动**。这里用 `VACUUM INTO`，它会把当前连接视角下
全部已提交的数据合并成一个干净的单文件——备份出来的就是一份完整可用的库。

恢复：停掉后端 → 把备份文件覆盖回 `data/docwise.db` → 删掉同目录的
`docwise.db-wal` / `docwise.db-shm`（旧 WAL 不能配新库文件）→ 重启后端。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import storage  # noqa: E402
from app.config import settings  # noqa: E402

BACKUP_GLOB = "docwise-*.db"
DEFAULT_KEEP = 7


def _source_path() -> Path:
    """从 DATABASE_URL 取出 SQLite 文件路径（只支持 sqlite:/// 形式）。"""
    url = settings.database_url
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise SystemExit(f"只支持 SQLite 备份，当前 DATABASE_URL={url}")
    path = Path(url[len(prefix) :])
    if not path.is_absolute():
        path = storage.BASE_DIR / path
    if not path.exists():
        raise SystemExit(f"数据库文件不存在：{path}")
    return path


def _existing_backups(out_dir: Path) -> list[Path]:
    return sorted(
        (p for p in out_dir.glob(BACKUP_GLOB) if p.is_file()),
        key=lambda p: p.stat().st_mtime,
    )


def _list(out_dir: Path) -> None:
    backups = _existing_backups(out_dir)
    if not backups:
        print(f"（{out_dir} 里还没有备份）")
        return
    print(f"{'文件':<34}{'大小':>10}  时间")
    for path in reversed(backups):
        stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        size_mb = path.stat().st_size / 1024 / 1024
        print(f"{path.name:<34}{size_mb:>8.2f}MB  {stamp}")


def _prune(out_dir: Path, keep: int) -> list[Path]:
    """只保留最近 keep 份，返回被删掉的。"""
    backups = _existing_backups(out_dir)
    removed: list[Path] = []
    for path in backups[:-keep] if keep > 0 else backups:
        path.unlink()
        removed.append(path)
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="docwise 数据库备份（VACUUM INTO）")
    parser.add_argument("--out", help="备份目录（默认 data/backups）")
    parser.add_argument(
        "--keep",
        type=int,
        default=DEFAULT_KEEP,
        help=f"保留最近几份（默认 {DEFAULT_KEEP}）",
    )
    parser.add_argument("--list", action="store_true", help="列出已有备份后退出")
    args = parser.parse_args()

    out_dir = Path(args.out) if args.out else storage.BACKUPS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.list:
        _list(out_dir)
        return 0

    source = _source_path()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = out_dir / f"docwise-{stamp}.db"
    if target.exists():
        raise SystemExit(f"同名备份已存在：{target}")

    con = sqlite3.connect(str(source))
    try:
        # VACUUM INTO 的路径要写成 SQL 字面量：单引号转义一次
        escaped = str(target).replace("'", "''")
        con.execute(f"VACUUM INTO '{escaped}'")
    finally:
        con.close()

    # 备份完立刻验一遍：能打开、能查、integrity 通过才算数
    check = sqlite3.connect(str(target))
    try:
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
        tasks = check.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    finally:
        check.close()
    if integrity != "ok":
        target.unlink(missing_ok=True)
        raise SystemExit(f"备份校验失败（integrity={integrity}），已删除该文件")

    size_kb = target.stat().st_size / 1024
    print(f"备份完成：{target}")
    print(f"  来源：{source}")
    print(f"  大小：{size_kb:.1f} KB，任务 {tasks} 条，integrity={integrity}")

    for path in _prune(out_dir, args.keep):
        print(f"  清理旧备份：{path.name}")
    print(f"  当前保留 {len(_existing_backups(out_dir))} 份（--keep {args.keep}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
