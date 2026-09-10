from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "docwise.db"


class Settings(BaseSettings):
    database_url: str = f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"

    # 翻译引擎（快/中档）与 DeepSeek 服务配置。从 .env 读取；会在启动时注入环境，
    # 使 worker 的子进程能读到（DOCWISE_ENGINE_* / DEEPSEEK_*）。
    docwise_engine_python: str | None = None
    docwise_engine_script: str | None = None
    docwise_engine_service: str | None = None
    docwise_engine_medium_python: str | None = None
    docwise_engine_medium_script: str | None = None
    docwise_engine_medium_service: str | None = None
    # 前端跨域白名单追加项（逗号分隔，如手机真机访问 http://192.168.1.5:5173）；
    # 默认已允许本地开发端口（5173/4173）。**同源部署（后端托管前端产物）用不上
    # CORS**，这里只在"前端与后端不同源"时才需要。
    docwise_cors_origins: str | None = None
    # 同源部署：由后端托管前端构建产物，一个地址同时提供页面与接口。
    # 是否托管；关掉就只提供 API（本地 vite dev 时无所谓）。
    docwise_serve_frontend: bool = True
    # 前端产物目录；留空 = 自动找 <仓库根>/frontend/dist。
    # 相对路径按仓库根解析（不是当前工作目录）。
    docwise_frontend_dist: str | None = None
    # 论文问答"全量入上下文"的字符数阈值：译文总字符数超过它时，
    # 降级为 FTS5 词法检索兜底（控制在上下文窗口与单问成本内）。
    docwise_ask_full_context_max_chars: int = 300_000

    # ---- 账号体系 ----
    # 会话有效期（天）：登录签发的令牌多久过期（访问时滑动续期）
    docwise_session_days: int = 30
    # 存量无主任务（user_id 为空）归属给哪个账号；不配则只在日志里提示
    docwise_legacy_owner: str | None = None
    # 打开后登录页出现「演示账号一键进入」（仅演示环境开，默认关）
    docwise_demo_autologin: bool = False
    # 演示账号用户名（配合上一项使用）
    docwise_demo_username: str = "demo"
    # 同一用户名 + IP 连续登录失败上限（超过锁 5 分钟）
    docwise_login_max_attempts: int = 5

    deepseek_api_key: str | None = None
    deepseek_model: str | None = None
    deepseek_base_url: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()


def _to_env() -> dict[str, str]:
    """把 .env 里的引擎/服务配置映射成环境变量名→值（供启动时注入）。"""
    return {
        "DOCWISE_ENGINE_PYTHON": settings.docwise_engine_python,
        "DOCWISE_ENGINE_SCRIPT": settings.docwise_engine_script,
        "DOCWISE_ENGINE_SERVICE": settings.docwise_engine_service,
        "DOCWISE_ENGINE_MEDIUM_PYTHON": settings.docwise_engine_medium_python,
        "DOCWISE_ENGINE_MEDIUM_SCRIPT": settings.docwise_engine_medium_script,
        "DOCWISE_ENGINE_MEDIUM_SERVICE": settings.docwise_engine_medium_service,
        "DEEPSEEK_API_KEY": settings.deepseek_api_key,
        "DEEPSEEK_MODEL": settings.deepseek_model,
        "DEEPSEEK_BASE_URL": settings.deepseek_base_url,
    }
