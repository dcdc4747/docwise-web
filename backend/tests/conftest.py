import os
import tempfile
import uuid
from pathlib import Path

import pytest

# 测试用独立临时库，避免依赖/污染 dev 库 backend/data（该目录在部分环境只读）。
# 每次测试会话用随机名，避免并行测试进程互踩。
_tmp = Path(tempfile.gettempdir()) / f"docwise_test_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.as_posix()}"

from app.db import Base, engine  # noqa: E402  (需在 DATABASE_URL 之后导入)


@pytest.fixture(autouse=True)
def _reset_db():
    """每个测试从空库开始，避免测试间顺序依赖（worker 会在测试中创建任务）。"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
