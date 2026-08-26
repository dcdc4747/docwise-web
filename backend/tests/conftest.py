import os
import tempfile
from pathlib import Path

# 测试用独立临时库，避免依赖/污染 dev 库 backend/data（该目录在部分环境只读）。
_tmp = Path(tempfile.gettempdir()) / "docwise_test.db"
_tmp.unlink(missing_ok=True)  # 每次测试会话从干净库开始
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.as_posix()}"
