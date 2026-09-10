import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from .config import BASE_DIR, _to_env, settings
from .db import Base, SessionLocal, engine, ensure_fts, get_db
from .deps import (
    get_current_user,
    get_user_for_events,
    get_user_for_files,
    load_owned_task,
)
from .engine import Tier
from .llm import extract_understanding
from .logging_setup import setup_logging
from .models import Task, TaskBlock, TaskUnderstanding, User
from .routers.admin import router as admin_router
from .routers.ask import router as ask_router
from .routers.auth import router as auth_router
from .worker import TaskEventBus, TranslationWorker

setup_logging()
logger = logging.getLogger(__name__)

UPLOAD_DIR = BASE_DIR / "data" / "uploads"

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    (BASE_DIR / "data").mkdir(exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _ensure_schema()
    ensure_fts()
    _inject_engine_env()
    with SessionLocal() as session:
        from .auth import purge_expired

        purge_expired(session)
    _assign_legacy_tasks()
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


def _status_value(status):
    return getattr(status, "value", status)


def _serialize_block(block: TaskBlock) -> dict:
    return {
        "block_id": block.block_id,
        "text": block.text,
        "status": _status_value(block.status),
        "translated": block.translated,
        "error": block.error,
    }


def _task_files(task: Task) -> dict[str, bool]:
    """结果文件是否就绪（供前端一次取全，省掉额外的 HEAD 探测请求）。"""
    return {
        "mono": bool(task.translated_path and Path(task.translated_path).exists()),
        "dual": bool(
            task.dual_translated_path and Path(task.dual_translated_path).exists()
        ),
    }


def _serialize_task(task: Task, blocks: list[TaskBlock] | None = None) -> dict:
    data = {
        "id": task.id,
        "filename": task.filename,
        "status": _status_value(task.status),
        "progress": task.progress,
        "tier": task.tier,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }
    if blocks is not None:
        data["error_message"] = task.error_message
        data["translated_path"] = task.translated_path
        data["dual_translated_path"] = task.dual_translated_path
        data["blocks"] = [_serialize_block(block) for block in blocks]
    return data


def _serialize_understanding(u: TaskUnderstanding | None) -> dict:
    if u is None:
        return {"status": "pending", "guide": None, "terms": [], "error": None}
    return {
        "status": u.status,
        "guide": json.loads(u.guide_json) if u.guide_json else None,
        "terms": json.loads(u.terms_json) if u.terms_json else [],
        "error": u.error,
    }


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


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


@app.get("/api/tasks")
def list_tasks(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """当前登录用户自己的任务（最多 50 条，新的在前）。"""
    rows = db.scalars(
        select(Task).where(Task.user_id == user.id).order_by(Task.id.desc()).limit(50)
    ).all()
    return [_serialize_task(task) for task in rows]


@app.get("/api/tasks/{task_id}")
def get_task(
    task_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """任务详情：块 + 结果文件就绪状态 + 导读/术语状态（供工作台一次取全）。"""
    task = load_owned_task(db, user, task_id)

    blocks = db.scalars(
        select(TaskBlock).where(TaskBlock.task_id == task.id).order_by(TaskBlock.id)
    ).all()
    data = _serialize_task(task, blocks)
    understanding = db.scalars(
        select(TaskUnderstanding).where(TaskUnderstanding.task_id == task.id)
    ).first()
    data["files_ready"] = _task_files(task)
    data["understanding_status"] = (
        understanding.status if understanding is not None else "pending"
    )
    return data


@app.api_route("/api/tasks/{task_id}/files/{kind}", methods=["GET", "HEAD"])
def get_task_file(
    task_id: int,
    kind: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_user_for_files)],
    download: bool = False,
):
    """返回结果文件（mono 纯中文 / dual 双语 PDF）供预览与下载。

    鉴权：Bearer，或 `?ticket=`（浏览器发起的 iframe/下载带不了请求头）。
    """
    task = load_owned_task(db, user, task_id)
    if kind not in ("mono", "dual"):
        raise HTTPException(status_code=400, detail="未知文件类型")

    raw = task.translated_path if kind == "mono" else task.dual_translated_path
    path = Path(raw) if raw else None
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="结果文件不存在")

    if download:
        stem = Path(task.filename).stem or "result"
        return FileResponse(
            path,
            media_type="application/pdf",
            filename=f"{stem}_{kind}.pdf",
        )
    return FileResponse(path, media_type="application/pdf")


@app.get("/api/tasks/{task_id}/events")
async def task_events(
    task_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_user_for_events)],
):
    """SSE 推送：实时进度；前端也可轮询 GET /api/tasks/{id} 兜底。

    鉴权：Bearer，或 `?ticket=`（EventSource 带不了请求头）。
    """
    task = load_owned_task(db, user, task_id)

    initial_status = _status_value(task.status)
    initial_progress = task.progress or 0.0
    initial_error = task.error_message
    bus = request.app.state.event_bus
    queue = bus.subscribe(task_id)

    async def stream():
        try:
            yield _sse_event(
                {
                    "type": initial_status,
                    "status": initial_status,
                    "progress": initial_progress,
                    "error": initial_error,
                }
            )
            if initial_status in ("completed", "failed"):
                return
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield _sse_event(event)
                if event.get("type") in ("completed", "failed"):
                    return
        except asyncio.CancelledError:
            pass
        finally:
            bus.unsubscribe(task_id, queue)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/tasks/upload", status_code=202)
async def create_task_upload(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    file: UploadFile = File(...),
    tier: str = Form("fast"),
    source_lang: str = Form("en"),
    target_lang: str = Form("zh"),
):
    """前端上传 PDF：保存文件后创建异步翻译任务（归属当前登录用户），返回任务卡。"""
    filename = Path(file.filename or "upload.pdf").name
    if file.content_type != "application/pdf" and not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")
    try:
        tier_value = Tier(tier).value
    except ValueError:
        raise HTTPException(status_code=400, detail=f"未知档位：{tier}") from None

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPLOAD_DIR / f"{uuid4().hex}_{filename}"
    dest.write_bytes(await file.read())

    task = Task(
        user_id=user.id,
        filename=filename,
        original_path=str(dest),
        source_lang=source_lang,
        target_lang=target_lang,
        tier=tier_value,
        status="pending",
        progress=0.0,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    logger.info("收到上传：%s（%s，task_id=%s）", filename, tier_value, task.id)
    request.app.state.worker.enqueue(task.id)
    return _serialize_task(task)


@app.get("/api/tasks/{task_id}/understanding")
def get_understanding(
    task_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """返回导读/术语表状态（惰性按需生成；未生成返回 pending）。"""
    load_owned_task(db, user, task_id)
    u = db.scalars(
        select(TaskUnderstanding).where(TaskUnderstanding.task_id == task_id)
    ).first()
    return _serialize_understanding(u)


@app.post("/api/tasks/{task_id}/understanding", status_code=200)
def compute_understanding(
    task_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """惰性生成导读/术语表：先取；未生成/失败则调用 LLM 抽取并缓存。幂等。"""
    load_owned_task(db, user, task_id)

    u = db.scalars(
        select(TaskUnderstanding).where(TaskUnderstanding.task_id == task_id)
    ).first()
    if u is not None and u.status == "ready":
        return _serialize_understanding(u)

    blocks = db.scalars(
        select(TaskBlock).where(TaskBlock.task_id == task_id).order_by(TaskBlock.id)
    ).all()
    items = [
        (b.block_id, b.translated or b.text)
        for b in blocks
        if (b.translated or b.text)
    ]
    if not items:
        raise HTTPException(status_code=400, detail="该任务没有可提炼的文本")

    if u is None:
        u = TaskUnderstanding(task_id=task_id)
        db.add(u)
    u.status = "pending"
    u.error = None
    db.commit()

    try:
        result = extract_understanding(items)
        u.guide_json = json.dumps(
            {
                k: result.get(k)
                for k in (
                    "research_question",
                    "method",
                    "conclusion",
                    "innovation",
                    "contribution",
                )
            },
            ensure_ascii=False,
        )
        u.terms_json = json.dumps(result.get("terms", []), ensure_ascii=False)
        u.status = "ready"
        u.error = None
    except Exception as exc:  # noqa: BLE001 - 失败降级为"暂无导读"，不影响主任务
        u.guide_json = None
        u.terms_json = None
        u.status = "failed"
        u.error = str(exc)
    db.commit()
    return _serialize_understanding(u)
