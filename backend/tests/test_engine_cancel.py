"""引擎层：取消正在跑的子进程 / 失败时留下可诊断的日志。

这里**不 mock 子进程**：真的起一个"睡 60 秒"的假引擎脚本，验证取消能在秒级把
它杀掉（E 批的核心功能——一篇论文要翻十几分钟，用户点"取消"必须立刻见效）。
沙盒环境下子进程输出重定向到文件（不用管道），也不写仓库目录。
"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path
from uuid import uuid4

from app.engine import CancelToken, TaskState, Tier, TranslateRequest
from app.engine.open_source import OpenSourceEngine

SLEEPER = """
import sys, time, json, pathlib
args = sys.argv[1:]
out = pathlib.Path(args[args.index("--output") + 1])
print("假引擎启动", flush=True)
time.sleep(60)
(out / "result.json").write_text(json.dumps({"status": "completed", "blocks": []}))
"""


def _engine_env(monkeypatch, script: Path) -> None:
    """把引擎指向"本机 python + 指定脚本"，绕开真实翻译服务。"""
    monkeypatch.setenv("DOCWISE_ENGINE_PYTHON", sys.executable)
    monkeypatch.setenv("DOCWISE_ENGINE_SCRIPT", str(script))
    monkeypatch.setenv("DOCWISE_ENGINE_SERVICE", "fake-service")
    monkeypatch.delenv("DOCWISE_ENGINE_MEDIUM_PYTHON", raising=False)
    monkeypatch.delenv("DOCWISE_ENGINE_MEDIUM_SCRIPT", raising=False)
    monkeypatch.delenv("DOCWISE_ENGINE_MEDIUM_SERVICE", raising=False)


def _workdir() -> Path:
    """系统临时目录下的工作目录。

    不用 pytest 的 tmp_path（部分受限环境不可写），也不用 mkdtemp（受限环境下
    mkdtemp 建出来的目录写不进去）；用与 conftest 相同的方式建目录。
    """
    path = Path(tempfile.gettempdir()) / f"docwise_engine_cancel_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_cancel_kills_running_engine_subprocess(monkeypatch) -> None:
    workdir = _workdir()
    script = workdir / "sleeper.py"
    script.write_text(SLEEPER, encoding="utf-8")
    _engine_env(monkeypatch, script)

    out_dir = workdir / "out"
    request = TranslateRequest(
        source_path=workdir / "fake.pdf", tier=Tier.FAST, output_dir=out_dir
    )
    cancel = CancelToken()
    result: list = []

    def run() -> None:
        result.append(OpenSourceEngine().translate(request, cancel))

    started = time.monotonic()
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    # 等引擎真的起来（日志里出现第一行）再取消，才算"取消正在跑的"
    log_file = out_dir / "engine.log"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if log_file.exists() and log_file.read_text(encoding="utf-8").strip():
            break
        time.sleep(0.05)
    cancel.cancel()
    thread.join(timeout=30)
    elapsed = time.monotonic() - started

    assert not thread.is_alive(), "取消后子进程没有停下来"
    # 产品要求：点"取消"要秒级见效，不能等引擎自己跑完（一篇论文十几分钟）
    assert elapsed < 8, f"取消响应太慢：{elapsed:.1f}s"
    assert result and result[0].status == TaskState.CANCELLED
    assert result[0].error == "已取消"


def test_missing_result_json_reports_log_tail(monkeypatch) -> None:
    """引擎没产出 result.json 时，失败原因里要带上日志尾部——出事必须看得见。"""
    workdir = _workdir()
    script = workdir / "silent.py"
    script.write_text(
        "import sys\nprint('引擎启动后直接退出', flush=True)\nsys.exit(3)\n",
        encoding="utf-8",
    )
    _engine_env(monkeypatch, script)

    request = TranslateRequest(
        source_path=workdir / "fake.pdf", tier=Tier.FAST, output_dir=workdir / "out2"
    )
    result = OpenSourceEngine().translate(request)

    assert result.status == TaskState.FAILED
    assert "result.json" in result.error
    assert "引擎启动后直接退出" in result.error  # 日志尾部被带出来了


def test_unconfigured_engine_fails_fast(monkeypatch) -> None:
    for key in (
        "DOCWISE_ENGINE_PYTHON",
        "DOCWISE_ENGINE_SCRIPT",
        "DOCWISE_ENGINE_SERVICE",
        "DOCWISE_ENGINE_MEDIUM_PYTHON",
        "DOCWISE_ENGINE_MEDIUM_SCRIPT",
        "DOCWISE_ENGINE_MEDIUM_SERVICE",
    ):
        monkeypatch.delenv(key, raising=False)

    workdir = _workdir()
    request = TranslateRequest(
        source_path=workdir / "fake.pdf", tier=Tier.MEDIUM, output_dir=workdir / "out3"
    )
    result = OpenSourceEngine().translate(request)

    assert result.status == TaskState.FAILED
    assert "未配置" in result.error
