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
