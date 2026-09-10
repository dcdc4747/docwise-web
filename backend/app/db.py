from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


connect_args = (
    {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
)
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_fts() -> None:
    """建 FTS5 词法检索表（M4 论文问答"长度/噪声超阈值"时的检索兜底）。

    外部内容表指向 task_blocks，insert/update/delete 触发器自动同步。
    为容忍分词器/结构变更，每次启动先整表重建（内容源在 task_blocks，
    rebuild 回填；开发库规模小，代价可忽略）。
    """
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.begin() as conn:
        for name in ("task_blocks_fts_ai", "task_blocks_fts_ad", "task_blocks_fts_au"):
            conn.execute(text(f"DROP TRIGGER IF EXISTS {name}"))
        conn.execute(text("DROP TABLE IF EXISTS task_blocks_fts"))
        conn.execute(
            text(
                "CREATE VIRTUAL TABLE task_blocks_fts USING fts5("
                "block_id UNINDEXED, text, translated, "
                "content='task_blocks', content_rowid='id', tokenize='trigram'"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS task_blocks_fts_ai "
                "AFTER INSERT ON task_blocks BEGIN "
                "INSERT INTO task_blocks_fts(rowid, block_id, text, translated) "
                "VALUES (new.id, new.block_id, new.text, new.translated); END"
            )
        )
        conn.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS task_blocks_fts_ad "
                "AFTER DELETE ON task_blocks BEGIN "
                "INSERT INTO task_blocks_fts(task_blocks_fts, rowid, block_id, text, "
                "translated) VALUES ('delete', old.id, old.block_id, old.text, "
                "old.translated); END"
            )
        )
        conn.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS task_blocks_fts_au "
                "AFTER UPDATE ON task_blocks BEGIN "
                "INSERT INTO task_blocks_fts(task_blocks_fts, rowid, block_id, text, "
                "translated) VALUES ('delete', old.id, old.block_id, old.text, "
                "old.translated); "
                "INSERT INTO task_blocks_fts(rowid, block_id, text, translated) "
                "VALUES (new.id, new.block_id, new.text, new.translated); END"
            )
        )
        conn.execute(
            text("INSERT INTO task_blocks_fts(task_blocks_fts) VALUES ('rebuild')")
        )
