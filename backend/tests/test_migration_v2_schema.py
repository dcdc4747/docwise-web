"""B1：形态 v2 数据层——**两套建表路径必须一模一样**。

`Base.metadata.create_all` 管**新库**，`scripts/migrate_v2_schema.py` 管**老库**。
两边字段只要差一点，就会出现"新装的能用、升级上来的炸"这种最难查的问题，
所以判据钉成测试：新库 `create_all` 的 `PRAGMA table_info` 与老库迁移后一致。

测试全部在 `tmp_path` 里自建库，**不碰 `backend/data/`**。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, inspect, select, text
from sqlalchemy.orm import Session

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db import Base  # noqa: E402
from app.models import Task, User  # noqa: E402
from scripts import migrate_v2_schema as mig  # noqa: E402

# 迁移自己的记账表：只在老库存在，不算"结构差异"
INTERNAL_TABLES = {"_migration_marker"}
# 本期一个字段都不许动的既有表
UNTOUCHED_TABLES = (
    "task_history",
    "task_blocks",
    "task_understanding",
    "users",
    "auth_sessions",
    "auth_tickets",
)


def _engine(tmp_path: Path, name: str) -> Engine:
    return create_engine(f"sqlite:///{(tmp_path / name).as_posix()}")


def _fresh_db(tmp_path: Path, name: str = "fresh.db") -> Engine:
    """新库路径：`create_all` 一把建出来。"""
    engine = _engine(tmp_path, name)
    Base.metadata.create_all(bind=engine)
    return engine


def _legacy_db(tmp_path: Path, name: str = "legacy.db") -> Engine:
    """老库路径：B1 之前的样子——没有那 11 张新表、没有 `reading_status`。

    造法：先 `create_all` 再把 B1 加的东西摘掉。这样既有表的定义与今天一致
    （B1 不许改它们），又确实少了新表与新列。
    """
    engine = _engine(tmp_path, name)
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            if table.name in mig.NEW_TABLES:
                conn.execute(text(f'DROP TABLE IF EXISTS "{table.name}"'))
        conn.execute(text(f"DROP INDEX IF EXISTS {mig.READING_STATUS_INDEX}"))
        conn.execute(text(f"ALTER TABLE tasks DROP COLUMN {mig.READING_STATUS}"))
    return engine


def _tables(engine: Engine) -> list[str]:
    names = inspect(engine).get_table_names()
    return sorted(name for name in names if name not in INTERNAL_TABLES)


def _table_info(engine: Engine, table: str) -> list[tuple]:
    """`PRAGMA table_info` 原样（含列序）。"""
    with engine.connect() as conn:
        rows = conn.execute(text(f'PRAGMA table_info("{table}")'))
        return [tuple(row) for row in rows]


def _column_names(engine: Engine, table: str) -> set[str]:
    return {row[1] for row in _table_info(engine, table)}


def _column_signature(engine: Engine, table: str, column: str) -> tuple:
    """某一列的 (类型, 非空, 默认值, 主键)——**不带 cid**，比对时不看列序。"""
    for row in _table_info(engine, table):
        if row[1] == column:
            return (row[2], row[3], row[4], row[5])
    raise AssertionError(f"{table}.{column} 不存在")


def _columns_by_name(engine: Engine) -> dict[str, dict[str, tuple]]:
    """表名 → {列名: (类型, 非空, 默认值, 主键)}。

    **不比列序**：老库里历次 `ALTER TABLE` 追加的列本来就和新建库顺序不同
    （比如 `tasks.user_id`），而列序在 SQLite 里没有语义。字段名、类型、约束、
    默认值这几项才是"两边一模一样"该管的东西。
    """
    return {
        table: {
            row[1]: (row[2], row[3], row[4], row[5])
            for row in _table_info(engine, table)
        }
        for table in _tables(engine)
    }


def _indexes(engine: Engine) -> dict[str, set[str]]:
    with engine.connect() as conn:
        inspector = inspect(conn)
        names = [t for t in inspector.get_table_names() if t not in INTERNAL_TABLES]
        return {t: {ix["name"] for ix in inspector.get_indexes(t)} for t in names}


def _marker_rows(engine: Engine) -> list[tuple]:
    if "_migration_marker" not in inspect(engine).get_table_names():
        return []
    with engine.connect() as conn:
        return [
            tuple(row)
            for row in conn.execute(
                text("SELECT name, done_at FROM _migration_marker ORDER BY name")
            )
        ]


def _builtin_rows(engine: Engine) -> list[tuple]:
    table = Base.metadata.tables["smart_collections"]
    with engine.connect() as conn:
        return [
            tuple(row)
            for row in conn.execute(
                select(
                    table.c.id,
                    table.c.user_id,
                    table.c.name,
                    table.c.query,
                    table.c.builtin,
                    table.c.sort,
                    table.c.created_at,
                ).order_by(table.c.id)
            )
        ]


def _add_users(engine: Engine, *usernames: str) -> list[int]:
    with Session(engine) as session:
        users = [User(username=name, password_hash="x") for name in usernames]
        session.add_all(users)
        session.commit()
        return [user.id for user in users]


def _migrate(engine: Engine, *args: str) -> int:
    return mig.main(["--database-url", str(engine.url), *args])


# ========== 判据（契约 §0 第 8 条） ==========


def test_new_db_and_migrated_legacy_have_identical_schema(tmp_path, capsys):
    """⭐ 新库 `create_all` 与老库迁移后的结构逐字段一致（两套路径都要通）。"""
    fresh = _fresh_db(tmp_path)
    legacy = _legacy_db(tmp_path)

    # 先证明"老库"造对了：没有新表、没有新列
    assert not set(_tables(legacy)) & set(mig.NEW_TABLES)
    assert _column_names(legacy, "tasks") == _column_names(fresh, "tasks") - {
        mig.READING_STATUS
    }

    assert _migrate(legacy, "--apply") == 0

    assert _tables(legacy) == _tables(fresh)
    # 新表是整张建出来的，连列序都要一致
    for name in mig.NEW_TABLES:
        assert _table_info(legacy, name) == _table_info(fresh, name), name
    # 全部表：列名 + 类型 + 非空 + 默认值 + 主键一致
    assert _columns_by_name(legacy) == _columns_by_name(fresh)
    # 索引也要一致（新表索引 + tasks 上那一列新加的索引）
    assert _indexes(legacy) == _indexes(fresh)
    assert capsys.readouterr().out.count("✓") >= 1


def test_reading_status_is_the_last_task_column(tmp_path):
    """`reading_status` 必须是 `tasks` 的最后一列。

    老库靠 `ALTER TABLE` 补列只能追加到末尾；模型里若不是最后，两套路径的列序就会分叉
    （列序虽无语义，但"新库和老库长得不一样"是会让人误判的）。
    """
    fresh = _fresh_db(tmp_path)
    columns = [row[1] for row in _table_info(fresh, "tasks")]
    assert columns[-1] == mig.READING_STATUS


def test_new_column_matches_contract(tmp_path):
    """新列的 DDL 照契约：VARCHAR(16) / 非空 / 默认 'todo' / 有索引。"""
    fresh = _fresh_db(tmp_path)
    assert _column_signature(fresh, "tasks", mig.READING_STATUS) == (
        "VARCHAR(16)",
        1,
        "'todo'",
        0,
    )
    assert mig.READING_STATUS_INDEX in _indexes(fresh)["tasks"]


# ---------------------------------------------------------------- 八条硬规矩


def test_dry_run_writes_nothing(tmp_path, capsys):
    """规矩 2/3：默认只预览——**一行不写**（连记账表都不建）。"""
    legacy = _legacy_db(tmp_path)
    before = _columns_by_name(legacy)
    before_tables = _tables(legacy)

    assert _migrate(legacy) == 0

    out = capsys.readouterr().out
    assert "预览模式" in out
    assert "待建表 11 张" in out
    assert _tables(legacy) == before_tables
    assert _columns_by_name(legacy) == before
    assert not inspect(legacy).has_table("_migration_marker")


def test_apply_is_idempotent_and_marks_migration(tmp_path, capsys):
    """规矩 4/5：跑第二遍什么都不做，且库里留下 `_migration_marker`。"""
    legacy = _legacy_db(tmp_path)
    _add_users(legacy, "alice")

    assert _migrate(legacy, "--apply") == 0
    schema = _columns_by_name(legacy)
    indexes = _indexes(legacy)
    markers = _marker_rows(legacy)
    builtins = _builtin_rows(legacy)
    assert [row[0] for row in markers] == [mig.MARKER]

    assert _migrate(legacy, "--apply") == 0
    out = capsys.readouterr().out

    assert "已是最新" in out
    assert _columns_by_name(legacy) == schema
    assert _indexes(legacy) == indexes
    assert _marker_rows(legacy) == markers
    # 内置集合不重种：id 与 created_at 一个都没变（重种会换 id / 改时间）
    assert _builtin_rows(legacy) == builtins


def test_restore_is_dry_run_by_default_and_reverts(tmp_path, capsys):
    """规矩 6：能撤；且 `--restore` 同样默认只预览。"""
    legacy = _legacy_db(tmp_path)
    before_columns = _columns_by_name(legacy)
    before_tables = _tables(legacy)

    assert _migrate(legacy, "--apply") == 0
    assert _tables(legacy) != before_tables

    assert _migrate(legacy, "--restore") == 0
    assert "预览模式" in capsys.readouterr().out
    assert set(_tables(legacy)) & set(mig.NEW_TABLES)  # 预览没删东西

    assert _migrate(legacy, "--restore", "--apply") == 0
    assert _tables(legacy) == before_tables
    assert _columns_by_name(legacy) == before_columns
    assert _marker_rows(legacy) == []


def test_builtin_smart_collections_seeded_once_per_user(tmp_path):
    """`smart_collections` 的三个内置规则：每个已有账号三条，且不重复种。"""
    legacy = _legacy_db(tmp_path)
    user_ids = _add_users(legacy, "alice", "bob")

    assert _migrate(legacy, "--apply") == 0
    assert _migrate(legacy, "--apply") == 0

    rows = _builtin_rows(legacy)
    assert len(rows) == len(user_ids) * len(mig.BUILTIN_SMART_COLLECTIONS)
    for user_id in user_ids:
        mine = [row for row in rows if row[1] == user_id]
        assert [row[2] for row in mine] == ["待读", "在读", "已读"]
        assert [row[5] for row in mine] == [0, 1, 2]
        assert all(row[4] is True for row in mine)
        assert [row[3] for row in mine] == [
            {"all": [{"field": "reading_status", "op": "eq", "value": value}]}
            for value in ("todo", "reading", "done")
        ]


def test_existing_tables_are_not_touched(tmp_path):
    """规矩：已有 7 张表一列未动——只有 `tasks` 末尾多一列。"""
    legacy = _legacy_db(tmp_path)
    before = {table: _table_info(legacy, table) for table in _tables(legacy)}

    assert _migrate(legacy, "--apply") == 0

    after = {table: _table_info(legacy, table) for table in _tables(legacy)}
    for table in UNTOUCHED_TABLES:
        assert after[table] == before[table], table
    assert after["tasks"][: len(before["tasks"])] == before["tasks"]
    assert [row[1] for row in after["tasks"]] == [
        row[1] for row in before["tasks"]
    ] + [mig.READING_STATUS]


def test_reading_status_defaults_to_todo(tmp_path):
    """默认值 `todo` 两头都要管：裸 SQL 靠 `server_default`，ORM 靠 Python 默认。"""
    legacy = _legacy_db(tmp_path)
    assert _migrate(legacy, "--apply") == 0

    with legacy.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tasks "
                "(filename, source_lang, target_lang, tier, status, progress) "
                "VALUES ('raw.pdf', 'en', 'zh', 'fast', 'pending', 0)"
            )
        )
        assert (
            conn.execute(
                text("SELECT reading_status FROM tasks WHERE filename='raw.pdf'")
            ).scalar_one()
            == "todo"
        )

    with Session(legacy) as session:
        task = Task(filename="orm.pdf")
        session.add(task)
        session.commit()
        assert task.reading_status == "todo"


def test_startup_column_patch_matches_model(tmp_path, monkeypatch):
    """老库启动补列（`_ensure_schema`）与 `create_all` 的同一列必须一模一样。

    这是第三条路径：`create_all`（新库）/ 迁移脚本（计划内升级）/ 启动补列
    （老库直接起服务）。三条给出的列定义必须相同，否则"升级过的库"和"新装的库"
    会在同一个字段上表现不同。
    """
    from app import main as app_main

    legacy = _legacy_db(tmp_path)
    fresh = _fresh_db(tmp_path)
    monkeypatch.setattr(app_main, "engine", legacy)

    app_main._ensure_schema()

    assert _column_signature(legacy, "tasks", mig.READING_STATUS) == _column_signature(
        fresh, "tasks", mig.READING_STATUS
    )
    assert mig.READING_STATUS_INDEX in _indexes(legacy)["tasks"]
    # 补列只补这一列，别的列不许被动
    assert _column_names(legacy, "tasks") == _column_names(fresh, "tasks")


@pytest.mark.parametrize("table", mig.NEW_TABLES)
def test_new_tables_exist_in_fresh_db(tmp_path, table):
    """新库路径本身就带这些表（漏建一张，这里就红）。"""
    assert table in _tables(_fresh_db(tmp_path, name=f"fresh_{table}.db"))
