"""FastAPI 入口：建库建表、启动 worker、健康检查、CORS、挂载各路由与前端产物。

E 批起任务路由已拆到 `app/routers/tasks.py`，这里只留"启动/运维/健康检查"。

初始化顺序（lifespan）：建目录 → 建表补列 → 建 FTS → 注入引擎环境变量 →
清过期会话/票据 → 归属存量任务 → 回收磁盘 → 起 worker。
"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, select, text

from . import storage, webapp
from .config import _to_env, settings
from .db import Base, SessionLocal, engine, ensure_fts
from .logging_setup import setup_logging
from .models import Task, User
from .routers.admin import router as admin_router
from .routers.ask import router as ask_router
from .routers.auth import router as auth_router
from .routers.tasks import router as tasks_router
from .worker import TaskEventBus, TranslationWorker

setup_logging()
logger = logging.getLogger(__name__)

# worker 心跳超过这个秒数视为不健康（循环卡死或已被杀）
WORKER_HEARTBEAT_STALE_SECONDS = 60.0


def _inject_engine_env() -> None:
    """把 .env 里的引擎/DeepSeek 配置注入环境，供 worker 子进程读取。

    不覆盖已显式设置的环境变量（$env: 优先级高于 .env）。
    """
    for key, value in _to_env().items():
        if value and not os.environ.get(key):
            os.environ[key] = value


def _ensure_schema() -> None:
    """为已存在的 SQLite 库补上新增列（create_all 只建表、不改表）。"""
    if not str(engine.url).startswith("sqlite"):
        return
    inspector = inspect(engine)
    if "tasks" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("tasks")}
    additions = {
        "user_id": "INTEGER",
        "source_lang": "VARCHAR(16) DEFAULT 'en'",
        "target_lang": "VARCHAR(16) DEFAULT 'zh'",
        "tier": "VARCHAR(16) DEFAULT 'fast'",
        "translated_path": "VARCHAR(1024)",
        "dual_translated_path": "VARCHAR(1024)",
        # F 批（诚实进度）：阶段 + 引擎自报剩余 + 起止时间
        "stage": "VARCHAR(16)",
        "eta_seconds": "INTEGER",
        "started_at": "DATETIME",
        "finished_at": "DATETIME",
    }
    with engine.begin() as conn:
        for column, ddl in additions.items():
            if column not in existing:
                conn.execute(text(f"ALTER TABLE tasks ADD COLUMN {column} {ddl}"))
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_tasks_user_id ON tasks (user_id)")
        )


def _assign_legacy_tasks() -> None:
    """把没有主人的老任务归属给指定账号（DOCWISE_LEGACY_OWNER）。

    不配该变量时只打日志提示——否则这些任务加完鉴权后就没人看得见了。
    """
    with SessionLocal() as session:
        orphans = session.scalars(select(Task).where(Task.user_id.is_(None))).all()
        if not orphans:
            return
        owner = (settings.docwise_legacy_owner or "").strip()
        if not owner:
            logger.warning(
                "有 %s 条无主任务（user_id 为空），未配置 DOCWISE_LEGACY_OWNER，"
                "登录后没人能看到它们",
                len(orphans),
            )
            return
        user = session.scalars(select(User).where(User.username == owner)).first()
        if user is None:
            logger.warning(
                "DOCWISE_LEGACY_OWNER=%s 账号不存在，%s 条无主任务仍未归属",
                owner,
                len(orphans),
            )
            return
        for task in orphans:
            task.user_id = user.id
        session.commit()
        logger.info("已把 %s 条无主任务归属给账号 %s", len(orphans), owner)


def _reclaim_disk() -> None:
    """启动时回收磁盘：孤儿结果目录 + 陈旧的引擎临时目录。

    只删"不属于任何任务"的目录——任务还在（哪怕失败）就绝不动它的产物，
    用户可能正要下载。清理本身失败不影响启动。
    """
    try:
        with SessionLocal() as session:
            known = set(session.scalars(select(Task.id)).all())
        orphans = storage.cleanup_orphan_outputs(known)
        temps = storage.cleanup_engine_temp_dirs()
        if orphans or temps:
            logger.info(
                "启动磁盘回收：孤儿结果目录 %s 个、陈旧引擎临时目录 %s 个",
                orphans,
                temps,
            )
    except Exception:  # noqa: BLE001 - 清理失败不能让服务起不来
        logger.exception("启动磁盘回收失败（忽略，不影响启动）")


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.DATA_DIR.mkdir(parents=True, exist_ok=True)
    storage.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    storage.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _ensure_schema()
    ensure_fts()
    _inject_engine_env()
    with SessionLocal() as session:
        from .auth import purge_expired

        purge_expired(session)
    _assign_legacy_tasks()
    _reclaim_disk()
    if settings.docwise_demo_autologin:
        logger.warning(
            "DOCWISE_DEMO_AUTOLOGIN 已开启：登录页可一键进入演示账号 %s（仅演示开）",
            settings.docwise_demo_username,
        )
    # 每个应用生命周期新建独立 worker/事件总线，避免 asyncio.Queue 跨事件循环绑定。
    app.state.event_bus = TaskEventBus()
    app.state.worker = TranslationWorker(app.state.event_bus)
    await app.state.worker.start()
    yield
    await app.state.worker.stop()


app = FastAPI(title="docwise-web", version="0.1.0", lifespan=lifespan)


def _cors_origins() -> list[str]:
    """跨域白名单：默认本地开发端口（Vite 5173 / preview 4173），
    可用 DOCWISE_CORS_ORIGINS（逗号分隔）追加手机真机访问等来源。"""
    origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ]
    extra = settings.docwise_cors_origins or ""
    origins += [item.strip() for item in extra.split(",") if item.strip()]
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ask_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(tasks_router)


def _database_writable() -> tuple[bool, str | None]:
    """真写一次数据库来判定可写（此前只读挂载时健康检查仍报"已连接"）。"""
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS _health_probe ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL)"
                )
            )
            conn.execute(
                text("INSERT INTO _health_probe(ts) VALUES (:ts)"),
                {"ts": datetime.now().isoformat(timespec="seconds")},
            )
            conn.execute(
                text(
                    "DELETE FROM _health_probe WHERE id NOT IN "
                    "(SELECT MAX(id) FROM _health_probe)"
                )
            )
        return True, None
    except Exception as exc:  # noqa: BLE001 - 健康检查本身不能抛异常
        return False, str(exc)


@app.get("/api/health")
def health(request: Request):
    """真健康检查：数据库可写？worker 还活着（心跳新鲜）？队列里排了几篇？"""
    db_ok, db_error = _database_writable()

    worker = getattr(request.app.state, "worker", None)
    heartbeat_age = worker.heartbeat_age if worker is not None else None
    worker_ok = bool(
        worker is not None
        and worker.is_alive()
        and heartbeat_age is not None
        and heartbeat_age < WORKER_HEARTBEAT_STALE_SECONDS
    )

    checks = {"database": db_ok, "worker": worker_ok}
    payload = {
        "status": "ok" if all(checks.values()) else "degraded",
        "service": "docwise-web",
        "version": "0.1.0",
        "checks": checks,
        "queue_size": worker.queue_size if worker is not None else None,
        "running_task_id": worker.current_task_id if worker is not None else None,
        "worker_heartbeat_age": (
            round(heartbeat_age, 1) if heartbeat_age is not None else None
        ),
        # 公开的登录选项（供登录页显示"演示账号一键进入"，不含任何敏感信息）
        "auth": {
            "demo_autologin": bool(settings.docwise_demo_autologin),
            "session_days": settings.docwise_session_days,
        },
    }
    if db_error:
        payload["database_error"] = db_error
    return payload


# 同源部署（后端托管前端产物）：**必须放在文件最后**——Starlette 按注册顺序匹配，
# 挂在 "/" 的静态托管写在前面会把后面定义的路由（含 /api/health）一起吃掉。
# 产物不存在时它自己跳过并打日志，不影响"只跑 API"的开发态。
webapp.mount_frontend(app)
