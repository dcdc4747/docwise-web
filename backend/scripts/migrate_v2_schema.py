"""一次性迁移：形态 v2 数据层——11 张新表 + `tasks.reading_status` 一列（2026-10-14）。

为什么"一次性建完"：`app/models.py` 是后端最大的热点，本期后面有 6 个任务要改它
（集合 / 标签 / 素材 / 台账 / 埋点 / 结构解析）。不一次建完，就是 6 个人轮流改同一个
文件。所以这一包把**本期全部新表**建齐，后面各包只加路由、不动模型。

为什么要有这个脚本（而不是只靠 `create_all`）：`Base.metadata.create_all` 只管
**新库**，老库不会自己长出列来（`create_all` 只建表、不改表）。老库靠
`app/main.py::_ensure_schema` 补列、靠本脚本可审计地建表 + 种内置数据。
两条路径的字段必须一模一样——判据在 `tests/test_migration_v2_schema.py`：
新库 `create_all` 的 `PRAGMA table_info` 与老库迁移后一致。

安全约定（照 `契约_数据模型_v1` §0 的八条硬规矩）：

1. **默认只预览**（打印将要做什么），加 `--apply` 才真写；
2. **幂等**：跑第二遍什么都不做；
3. 跑过会往 `_migration_marker` 记一笔（`v2_schema_20261014`），重复跑直接跳过；
4. `--restore` 反向操作（删表 / 删列 / 清标记），同样**默认只预览**；
5. **不引 alembic**、不加依赖、不动 `backend/data/` 里的真实数据文件——
   只通过 SQL 改库里的行与结构；
6. 新表 DDL 直接取自模型（`Base.metadata`），保证与 `create_all` 一字不差。

用法：

    cd backend
    .venv/Scripts/python -m scripts.migrate_v2_schema                     # 预览
    .venv/Scripts/python -m scripts.migrate_v2_schema --apply             # 执行
    .venv/Scripts/python -m scripts.migrate_v2_schema --restore --apply   # 撤销

（`--database-url` 可指向别的库文件先在备份上演练；默认用 `settings.database_url`。）
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import Engine, create_engine, inspect, select, text  # noqa: E402

from app import models  # noqa: E402,F401  (导入即把表结构注册进 Base.metadata)
from app.config import settings  # noqa: E402
from app.db import Base  # noqa: E402
from app.timeutil import utc_now  # noqa: E402

MARKER = "v2_schema_20261014"
READING_STATUS = "reading_status"
READING_STATUS_INDEX = "ix_tasks_reading_status"
# 与 `models.Task.reading_status` 生成的建表语句逐字一致：
# String(16) + server_default "todo" + nullable=False
READING_STATUS_DDL = "VARCHAR(16) DEFAULT 'todo' NOT NULL"

# 本期新增的表（以名单为准，不写"10 张"这种要人数出来的总数）
NEW_TABLES: tuple[str, ...] = (
    "collections",
    "task_collections",
    "tags",
    "task_tags",
    "smart_collections",
    "materials",
    "drafts",
    "citations",
    "memory_events",
    "block_edits",
    "block_exposures",
)

# 内置三条智能集合（`builtin: true`，迁移时种下）：规则即数据。
BUILTIN_SMART_COLLECTIONS: tuple[tuple[str, dict], ...] = (
    ("待读", {"all": [{"field": READING_STATUS, "op": "eq", "value": "todo"}]}),
    ("在读", {"all": [{"field": READING_STATUS, "op": "eq", "value": "reading"}]}),
    ("已读", {"all": [{"field": READING_STATUS, "op": "eq", "value": "done"}]}),
)


@dataclass
class Plan:
    """将要做什么（**dry-run 打印的就是它**，apply 执行的是它）。"""

    database: str
    marker_done: bool = False
    missing_tables: list[str] = field(default_factory=list)
    missing_column: bool = False
    missing_index: bool = False
    # (user_id, 集合名)：老库里的账号各补三条内置智能集合
    missing_builtins: list[tuple[int, str]] = field(default_factory=list)
    user_count: int = 0
    dropped_on_restore: list[str] = field(default_factory=list)

    def is_noop(self) -> bool:
        return not (
            self.missing_tables
            or self.missing_column
            or self.missing_index
            or self.missing_builtins
        )


def connect(database_url: str | None = None) -> Engine:
    """打开目标库（默认就是 `DATABASE_URL` 指的那个）。"""
    return create_engine(database_url or settings.database_url)


def _relax_stdout() -> None:
    """把输出切到 UTF-8。

    Windows 控制台默认 GBK（cp936），打印 `✓` / `✗` 会直接抛 `UnicodeEncodeError`
    ——**在写完库之后崩**，最容易被读成"迁移失败了"。这里兜一下，别再让输出编码
    影响迁移本身的判断。
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - 拿不到真 stdout（被重定向/被包装）就算了
        pass


def _marker_done(conn, marker: str = MARKER) -> bool:
    """`_migration_marker` 里有没有这一笔（**只读**，dry-run 也安全）。"""
    if not inspect(conn).has_table("_migration_marker"):
        return False
    row = conn.execute(
        text("SELECT 1 FROM _migration_marker WHERE name = :name"), {"name": marker}
    ).first()
    return row is not None


def _column_names(conn, table: str) -> set[str]:
    return {col["name"] for col in inspect(conn).get_columns(table)}


def _index_names(conn, table: str) -> set[str]:
    return {ix["name"] for ix in inspect(conn).get_indexes(table)}


def plan(conn, database: str = "") -> Plan:
    """算出要做什么——**不写任何东西**（dry-run 与 apply 共用这一份判断）。"""
    result = Plan(database=database, marker_done=_marker_done(conn))
    inspector = inspect(conn)
    existing = set(inspector.get_table_names())
    result.missing_tables = [name for name in NEW_TABLES if name not in existing]

    if "tasks" in existing:
        result.missing_column = READING_STATUS not in _column_names(conn, "tasks")
        result.missing_index = READING_STATUS_INDEX not in _index_names(conn, "tasks")

    if "users" in existing:
        user_ids = [
            row[0] for row in conn.execute(select(Base.metadata.tables["users"].c.id))
        ]
        result.user_count = len(user_ids)
        if user_ids:
            result.missing_builtins = _missing_builtins(conn, user_ids, existing)

    result.dropped_on_restore = [name for name in NEW_TABLES if name in existing]
    return result


def _missing_builtins(
    conn, user_ids: list[int], existing: set[str]
) -> list[tuple[int, str]]:
    """哪些账号还缺内置智能集合（已有的一律不重种，天然幂等）。"""
    if "smart_collections" not in existing:
        return [
            (uid, name) for uid in user_ids for name, _ in BUILTIN_SMART_COLLECTIONS
        ]

    table = Base.metadata.tables["smart_collections"]
    rows = conn.execute(
        select(table.c.user_id, table.c.name).where(table.c.builtin.is_(True))
    ).all()
    have = {(row[0], row[1]) for row in rows}
    return [
        (uid, name)
        for uid in user_ids
        for name, _ in BUILTIN_SMART_COLLECTIONS
        if (uid, name) not in have
    ]


def apply(conn, todo: Plan) -> None:
    """真写：建表 → 补列 → 建索引 → 种内置 → 记标记。

    **幂等**：每一步都先判断存在性，重复跑只是白判断一轮。
    """
    if todo.missing_tables:
        _create_tables(conn, todo.missing_tables)
    if todo.missing_column:
        conn.execute(
            text(f"ALTER TABLE tasks ADD COLUMN {READING_STATUS} {READING_STATUS_DDL}")
        )
    if todo.missing_column or todo.missing_index:
        conn.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS {READING_STATUS_INDEX} "
                f"ON tasks ({READING_STATUS})"
            )
        )
    if todo.missing_builtins:
        _seed_builtin_smart_collections(conn, todo.missing_builtins)
    _write_marker(conn)


def _create_tables(conn, names: list[str]) -> None:
    """按依赖顺序建表；DDL 取自模型——与 `create_all` 一字不差。"""
    wanted = set(names)
    for table in Base.metadata.sorted_tables:
        if table.name in wanted:
            table.create(bind=conn, checkfirst=True)


def _seed_builtin_smart_collections(conn, missing: list[tuple[int, str]]) -> None:
    table = Base.metadata.tables["smart_collections"]
    names = [name for name, _ in BUILTIN_SMART_COLLECTIONS]
    now = utc_now()
    for user_id, name in missing:
        query = next(q for n, q in BUILTIN_SMART_COLLECTIONS if n == name)
        conn.execute(
            table.insert().values(
                user_id=user_id,
                name=name,
                query=query,
                builtin=True,
                sort=names.index(name),
                created_at=now,
            )
        )


def _write_marker(conn) -> None:
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS _migration_marker "
            "(name TEXT PRIMARY KEY, done_at TEXT)"
        )
    )
    conn.execute(
        text("INSERT OR REPLACE INTO _migration_marker(name, done_at) VALUES (:n, :d)"),
        {"n": MARKER, "d": utc_now().isoformat(timespec="seconds")},
    )


def restore(conn) -> list[str]:
    """反向操作：删新表 / 删列 / 删索引 / 清标记（是否真执行由调用方决定）。"""
    dropped: list[str] = []
    existing = set(inspect(conn).get_table_names())
    # 反依赖顺序删，避免外键引用悬空
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in NEW_TABLES and table.name in existing:
            conn.execute(text(f'DROP TABLE IF EXISTS "{table.name}"'))
            dropped.append(table.name)

    if "tasks" in existing:
        conn.execute(text(f"DROP INDEX IF EXISTS {READING_STATUS_INDEX}"))
        if READING_STATUS in _column_names(conn, "tasks"):
            try:
                conn.execute(text(f"ALTER TABLE tasks DROP COLUMN {READING_STATUS}"))
            except Exception as exc:  # noqa: BLE001 - 老 SQLite 不支持 DROP COLUMN
                print(
                    f"！这个 SQLite 不支持 DROP COLUMN（{exc}）——"
                    f"tasks.{READING_STATUS} 保留，其余已撤。"
                )

    if inspect(conn).has_table("_migration_marker"):
        conn.execute(
            text("DELETE FROM _migration_marker WHERE name = :name"), {"name": MARKER}
        )
    return dropped


def _print_plan(todo: Plan, *, restoring: bool) -> None:
    print(f"数据库：{todo.database}")
    print(f"迁移标记：{MARKER}（库里{'已有' if todo.marker_done else '没有'}）")
    if restoring:
        targets = todo.dropped_on_restore
        print(f"\n将删除 {len(targets)} 张新表：{', '.join(targets) or '（无）'}")
        print(f"将删除列：tasks.{READING_STATUS}（含索引 {READING_STATUS_INDEX}）")
        print(f"将清除迁移标记：{MARKER}")
        return

    print(f"\n库里账号 {todo.user_count} 个。")
    print(
        f"待建表 {len(todo.missing_tables)} 张："
        f"{', '.join(todo.missing_tables) or '（无，已建齐）'}"
    )
    column_state = (
        f"缺列，将补 {READING_STATUS_DDL}" if todo.missing_column else "已就位"
    )
    index_state = "缺，将建" if todo.missing_index else "已就位"
    print(
        f"tasks.{READING_STATUS}：{column_state}；"
        f"索引 {READING_STATUS_INDEX}：{index_state}"
    )
    print(f"待种内置智能集合 {len(todo.missing_builtins)} 条：")
    for user_id, name in todo.missing_builtins[:6]:
        print(f"  账号 {user_id} ← {name}")
    if len(todo.missing_builtins) > 6:
        print(f"  …（还有 {len(todo.missing_builtins) - 6} 条）")


def main(argv: list[str] | None = None) -> int:
    _relax_stdout()
    parser = argparse.ArgumentParser(
        description="形态 v2 数据层迁移（建表 / 补列 / 种内置；默认只预览）"
    )
    parser.add_argument("--apply", action="store_true", help="真写库（默认只预览）")
    parser.add_argument(
        "--restore",
        action="store_true",
        help="反向操作：删新表 / 删列（同样默认只预览）",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="目标库（默认用 DATABASE_URL，可指向备份文件先演练）",
    )
    args = parser.parse_args(argv)

    engine = connect(args.database_url)
    with engine.begin() as conn:
        todo = plan(conn, database=str(engine.url))
        _print_plan(todo, restoring=args.restore)

        if args.restore:
            if not args.apply:
                print("\n（预览模式，什么都没改。要真撤销加 --apply）")
                return 0
            dropped = restore(conn)
            print(f"\n✓ 已撤销：删表 {len(dropped)} 张、清列与标记。")
            return 0

        if todo.marker_done and todo.is_noop():
            print("\n✓ 已是最新（标记在、结构齐）——什么都不用做。")
            return 0
        if todo.is_noop():
            print("\n✓ 结构已齐——不重复建。")
            return 0
        if not args.apply:
            print("\n（预览模式，什么都没写。要真执行加 --apply）")
            return 0

        apply(conn, todo)
        print(
            f"\n✓ 完成：建表 {len(todo.missing_tables)} 张、"
            f"补列 {'是' if todo.missing_column else '否'}、"
            f"种内置 {len(todo.missing_builtins)} 条、标记 {MARKER}。"
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
