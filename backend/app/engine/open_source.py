from __future__ import annotations

import json
import locale
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from .base import (
    BlockState,
    BlockStatus,
    CancelToken,
    TaskState,
    TranslateRequest,
    TranslationEngine,
    TranslationResult,
)

logger = logging.getLogger(__name__)

# 兜底临时目录的前缀（storage.ENGINE_TEMP_PREFIX 与之一致）
ENGINE_TEMP_PREFIX = "docwise_engine_"


class OpenSourceEngine(TranslationEngine):
    """成熟开源翻译引擎的适配器，对应快档。

    通过子进程调用外部包装脚本，产出 mono(单语即中文)/dual(双语) PDF，
    并抽取源文文字块作为"每块状态"。

    说明（阶段 1 粗粒度）：外部引擎不暴露"每块成败"，这里以
    "整体翻译完成→块标记成功、失败→块标记失败"作为粗粒度状态，
    后续再细化到"某块截断/溢出"级别。
    """

    name = "open-source"
    # 档位专属环境变量前缀：中档用 DOCWISE_ENGINE_MEDIUM_*，快档用 DOCWISE_ENGINE_*
    env_prefix = "DOCWISE_ENGINE"
    # 子进程轮询间隔：太短空耗 CPU，太长"取消"要等很久才生效
    POLL_INTERVAL_SECONDS = 0.5
    # 单次翻译超时（秒）：超时按失败落库，不允许无声无息地挂着
    TIMEOUT_SECONDS = 1800

    def _env(self, key: str) -> str | None:
        """读取档位专属环境变量；未设置时回退到基础变量（快档）。

        例：中档读 DOCWISE_ENGINE_MEDIUM_SCRIPT，没配就回退 DOCWISE_ENGINE_SCRIPT，
        这样没有专门配置中档时也能跑（默认与快档行为一致）。
        """
        value = os.environ.get(f"{self.env_prefix}_{key}")
        if value is None and self.env_prefix != "DOCWISE_ENGINE":
            value = os.environ.get(f"DOCWISE_ENGINE_{key}")
        return value

    def translate(
        self, request: TranslateRequest, cancel: CancelToken | None = None
    ) -> TranslationResult:
        python = self._env("PYTHON")
        script = self._env("SCRIPT")
        service = self._env("SERVICE")
        if not python or not script or not service:
            return self._failed(
                request,
                "未配置 DOCWISE_ENGINE_PYTHON / DOCWISE_ENGINE_SCRIPT / "
                "DOCWISE_ENGINE_SERVICE",
            )

        # 结果目录：默认 data/outputs/{task_id}（由调度器传），删任务时整体清理
        out_dir = request.output_dir or self._temp_output_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        result_file = out_dir / "result.json"
        log_file = out_dir / "engine.log"
        # 上一轮留下的 result.json 必须先清掉，否则会把旧结果当成本轮结果
        result_file.unlink(missing_ok=True)

        cmd = [
            python,
            script,
            "--input", str(request.source_path),
            "--output", str(out_dir),
            "--lang-in", request.source_lang,
            "--lang-out", request.target_lang,
            "--service", service,
            "--thread", "2",
        ]
        # 输出重定向到文件（不走管道：管道写满会互相卡死，日志也留得住）
        # PYTHONIOENCODING：Windows 下子进程默认按 GBK 写日志，读回来就是乱码，
        # 强制 UTF-8 才能用它排查问题（对非 Python 引擎无副作用）。
        child_env = os.environ.copy()
        child_env["PYTHONIOENCODING"] = "utf-8"
        child_env["PYTHONUTF8"] = "1"
        with log_file.open("w", encoding="utf-8", errors="replace") as handle:
            proc = subprocess.Popen(
                cmd, env=child_env, stdout=handle, stderr=subprocess.STDOUT
            )
            outcome = self._wait_for_exit(proc, cancel)

        if outcome == "cancelled":
            logger.info("引擎子进程已终止（用户取消）：%s", request.source_path)
            return TranslationResult(
                task_id=str(request.source_path),
                translated_path=None,
                blocks=[],
                status=TaskState.CANCELLED,
                progress=0.0,
                error="已取消",
            )
        if outcome == "timeout":
            return self._failed(
                request,
                f"引擎超过 {self.TIMEOUT_SECONDS} 秒未结束，已强制终止；"
                f"日志尾部：{self._log_tail(log_file)}",
            )

        if not result_file.exists():
            return self._failed(
                request,
                f"引擎未返回 result.json（退出码 {proc.returncode}）；"
                f"日志尾部：{self._log_tail(log_file)}",
            )

        payload = json.loads(result_file.read_text(encoding="utf-8"))
        completed = payload.get("status") == "completed"
        blocks = [
            BlockStatus(
                block_id=item["block_id"],
                text=item["text"],
                status=BlockState.SUCCESS if completed else BlockState.FAILED,
                translated=item.get("translated"),
            )
            for item in payload.get("blocks", [])
        ]

        translated = Path(payload["mono"]) if payload.get("mono") else None
        dual = Path(payload["dual"]) if payload.get("dual") else None
        if translated is None and dual is not None:
            translated = dual

        return TranslationResult(
            task_id=str(request.source_path),
            translated_path=translated,
            dual_path=dual,
            blocks=blocks,
            status=TaskState.COMPLETED if completed else TaskState.FAILED,
            progress=1.0 if completed else 0.0,
            error=payload.get("error"),
        )

    def _failed(self, request: TranslateRequest, error: str) -> TranslationResult:
        return TranslationResult(
            task_id=str(request.source_path),
            translated_path=None,
            blocks=[],
            status=TaskState.FAILED,
            error=error,
        )

    @staticmethod
    def _temp_output_dir() -> Path:
        """没给 output_dir 时的兜底目录（测试/一次性调用用）。

        用 `mkdir` 而不是 `mkdtemp`：受限环境（沙盒）里 mkdtemp 建出来的目录
        写不进去，而调度器给的 `data/outputs/{task_id}` 是正常路径。
        """
        path = Path(tempfile.gettempdir()) / f"{ENGINE_TEMP_PREFIX}{uuid4().hex}"
        return path

    def _wait_for_exit(self, proc: subprocess.Popen, cancel: CancelToken | None) -> str:
        """等待子进程结束，返回 done / cancelled / timeout。

        等待期间轮询取消信号，这样"取消正在跑的翻译"能在半秒级生效，
        而不是等引擎自己跑完（一篇论文十几分钟）。
        """
        started = time.monotonic()
        while True:
            if proc.poll() is not None:
                return "done"
            if cancel is not None and cancel.cancelled:
                self._terminate(proc)
                return "cancelled"
            if time.monotonic() - started > self.TIMEOUT_SECONDS:
                logger.warning(
                    "引擎子进程超时（%s 秒），强制终止：pid=%s",
                    self.TIMEOUT_SECONDS,
                    proc.pid,
                )
                self._terminate(proc)
                return "timeout"
            if cancel is not None:
                cancel.wait(self.POLL_INTERVAL_SECONDS)
            else:
                time.sleep(self.POLL_INTERVAL_SECONDS)

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        """终止引擎子进程。

        Windows 下先试 `taskkill /T` 连整棵进程树一起杀（引擎自己可能还开了子进程），
        再**无论成败**都对直接子进程补一发 terminate/kill —— taskkill 在受限环境里
        可能起不来，只靠它会把"取消"拖成十几秒。
        """
        if proc.poll() is not None:
            return
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    check=False,
                )
            except Exception:  # noqa: BLE001 - 杀不干净也不能把取消流程带崩
                logger.warning("taskkill 不可用，改用 terminate 直接结束引擎进程")
        if proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            logger.warning("terminate 失败，改用 kill：pid=%s", proc.pid)
        if proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.error("引擎子进程无法终止：pid=%s", proc.pid)

    @staticmethod
    def _read_engine_log(path: Path) -> str:
        """读引擎日志：先按 UTF-8，再退到本机默认编码（老引擎可能按 GBK 写）。"""
        try:
            raw = path.read_bytes()
        except OSError:
            return ""
        for encoding in ("utf-8", locale.getpreferredencoding(False)):
            try:
                return raw.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return raw.decode("utf-8", errors="replace")

    @staticmethod
    def _log_tail(path: Path, limit: int = 600) -> str:
        """取引擎日志尾部，让失败原因在任务卡上直接看得见。"""
        text = OpenSourceEngine._read_engine_log(path).strip()
        if not text:
            return "（日志为空）" if path.exists() else "（无日志）"
        return text[-limit:]
