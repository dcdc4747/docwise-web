import os
import tempfile
import uuid
from pathlib import Path

# 测试用独立临时库，避免依赖/污染 dev 库 backend/data（该目录在部分环境只读）。
# 每次测试会话用随机名，避免并行测试进程互踩。
_tmp = Path(tempfile.gettempdir()) / f"docwise_test_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.as_posix()}"
