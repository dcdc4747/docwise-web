"""演示库策展：把"能代表产品"的几篇留下，其余**藏起来**（不删）。

为什么要做：库里 40 多个任务里，绝大多数是 2026-09-30 之前传的——那些任务**没有块级译文**
（段落精读只能显示英文）、也**没有版面信号与区域**（认不出章节标题、没有目录）。
摆在一个列表里，看的人会以为"产品就这样"。策展＝列表里只留几篇像样的，
**数据一个字节不删**（`archived_at` 只影响列表接口；详情/下载/问答照旧可用，随时恢复）。

安全约定（与 `fix_timestamps_utc.py` 同一套）：
- **默认只预览**，`--apply` 才写；
- `--restore` 反向操作（全部取消归档），同样默认只预览；
- 只有"没被 keep 的"才会被归档；**已经在归档状态的不重复动**（幂等）。

用法：

    cd backend
    .venv/Scripts/python -m scripts.curate_demo_library                    # 预览
    .venv/Scripts/python -m scripts.curate_demo_library --apply            # 执行
    .venv/Scripts/python -m scripts.curate_demo_library --restore --apply  # 全部恢复
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Task  # noqa: E402

# 上传时落盘的文件名形如 `4f32f1858a884417b5e7bc6920ebdb15_pdf_sample_01.pdf`
_STORAGE_PREFIX = re.compile(r"^[0-9a-f]{32}_")

# 默认留下的几篇：覆盖产品要展示的四条路（外文长文 / 外文短文 / 中文文献 / 扫描件）。
# 想换就 --keep 自己传 id。
DEFAULT_KEEP = {
    41: "化学 arXiv（外文·17 页）：题名 + 30 条章节标题 + 图注 + 目录 + 版面区域",
    42: "数学 arXiv（外文·第二篇）：19 条章节标题",
    43: "sample_01（外文·短文）：题名 / 图注 / 作者行不再误判",
    38: "cn-layout-test（中文文献·不翻译）：23 条中文标题",
    33: "scan-cn-notice2（中文扫描件）：OCR 通道 + 诚实提示",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="演示库策展（归档/恢复，默认只预览）")
    parser.add_argument("--apply", action="store_true", help="真写库（默认只预览）")
    parser.add_argument(
        "--keep",
        default=",".join(str(i) for i in DEFAULT_KEEP),
        help="要留在列表里的任务 id（逗号分隔）",
    )
    parser.add_argument(
        "--restore", action="store_true", help="取消全部归档（反向操作）"
    )
    parser.add_argument(
        "--tidy-names",
        action="store_true",
        help="把留下的那几篇文件名里「存储用的 32 位十六进制前缀」去掉（只改显示名）",
    )
    args = parser.parse_args()

    keep = {int(part) for part in args.keep.split(",") if part.strip()}
    now = datetime.now(UTC).replace(tzinfo=None)

    with SessionLocal() as session:
        tasks = session.scalars(select(Task).order_by(Task.id)).all()
        archived = [t for t in tasks if t.archived_at is not None]
        visible = [t for t in tasks if t.archived_at is None]

        if args.restore:
            print(f"库里 {len(tasks)} 个任务，当前归档 {len(archived)} 个")
            if not archived:
                print("没有需要恢复的。")
                return 0
            print("将恢复：" + "、".join(f"#{t.id}" for t in archived))
            if not args.apply:
                print("\n（预览模式，什么都没改。要真执行加 --apply）")
                return 0
            for task in archived:
                task.archived_at = None
            session.commit()
            print(f"\n✓ 已恢复 {len(archived)} 个任务")
            return 0

        unknown = keep - {t.id for t in tasks}
        if unknown:
            print(f"✗ --keep 里有库里不存在的 id：{sorted(unknown)}")
            return 1

        print(
            f"库里 {len(tasks)} 个任务｜当前列表可见 {len(visible)} 个｜"
            f"已归档 {len(archived)} 个"
        )
        print("\n留下（列表可见）：")
        for task_id in sorted(keep):
            print(f"  #{task_id:<3} {DEFAULT_KEEP.get(task_id, '')}")

        to_archive = [t for t in tasks if t.id not in keep and t.archived_at is None]
        print(f"\n将归档 {len(to_archive)} 个（列表里不再显示，数据保留）：")
        for task in to_archive[:8]:
            print(
                f"  #{task.id:<3} {task.filename[:40]:<40} "
                f"{task.status:<9} {task.created_at}"
            )
        if len(to_archive) > 8:
            print(f"  …… 还有 {len(to_archive) - 8} 个")

        if not args.apply:
            print("\n（预览模式，什么都没改。要真执行加 --apply）")
            return 0
        for task in to_archive:
            task.archived_at = now
        if args.tidy_names:
            # 上传时磁盘上的文件名是「32 位十六进制前缀_原名」，有几篇任务的
            # `filename` 记的是那份带前缀的存储名（显示出来很难看）。**只改显示名**，
            # 磁盘文件与下载路径都不动（下载走 task_id + 实际路径，不看这个字段）。
            for task in tasks:
                if task.id in keep and _STORAGE_PREFIX.match(task.filename or ""):
                    old = task.filename
                    task.filename = _STORAGE_PREFIX.sub("", old)
                    print(f"  改名 #{task.id}: {old} → {task.filename}")
        session.commit()

        still_visible = session.scalars(
            select(Task).where(Task.archived_at.is_(None))
        ).all()
        print(f"\n✓ 归档 {len(to_archive)} 个；列表现在可见 {len(still_visible)} 个：")
        for task in sorted(still_visible, key=lambda t: -t.id):
            print(f"  #{task.id:<3} {task.filename[:48]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
