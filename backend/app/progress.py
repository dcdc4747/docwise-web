"""诚实进度：从引擎日志里读出**真实**进度，读不出就说读不出。

背景：引擎是子进程，我们只能通过它打到 stdout/stderr 的输出来了解它跑到哪了。
引擎用 tqdm 打进度条，我们把子进程的 stdout/stderr 一起重定向到
`data/outputs/{task_id}/engine.log`（见 `engine/open_source.py`），因此可以解析：

    20%|██        | 2/10 [00:01<00:05,  1.44it/s]

几个要点（都是实测出来的，不是猜的）：

- tqdm 用 `\\r` 原地重绘进度条（非 tty 时行尾也可能是 `\\n`），所以必须按 `[\\r\\n]+`
  切分，否则整条日志会是"一行"，只认得第一个进度条；
- 单位是**页**：引擎侧是 `tqdm(total=total_pages)` + 每页 `update()`；
- 引擎可能分多次跑（先出单语再出双语），进度条会重新出现，因此"取最后一条"；
  进度回退由调用方决定怎么处理（我们落库时只增不减，避免进度条来回跳）。

**绝不编造**：解析不出就返回 None，由上层显示"引擎还没报进度"。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# 一条 tqdm 进度条：`2/10 [00:01<00:05,  1.44it/s]`
# 时间部分可能是 `?`（未知），速率也可能是 `?it/s`
_BAR_RE = re.compile(
    r"(?P<done>\d+)\s*/\s*(?P<total>\d+)\s*"
    r"\[(?P<elapsed>[0-9:?]+)<(?P<remaining>[0-9:?]+)"
    r"(?:,\s*(?P<rate>[0-9.]+|\?)\s*it/s)?\]"
)

# 只读日志尾部：进度条一直在重绘，真正有用的永远是最后几行
_TAIL_BYTES = 8192


@dataclass(frozen=True)
class EngineProgress:
    """引擎自报的进度（`percent` 是我们按 done/total 算的，其余都是引擎原话）。"""

    done: int
    total: int
    percent: float
    elapsed_seconds: int | None
    eta_seconds: int | None
    rate: float | None
    raw: str

    @property
    def label(self) -> str:
        """给人看的一句话，如"第 2/10 页"。"""
        return f"第 {self.done}/{self.total} 页"


def _to_seconds(text: str | None) -> int | None:
    """tqdm 的时间段（`00:05` / `1:02:03` / `?`）→ 秒；未知返回 None。"""
    if not text or "?" in text:
        return None
    parts = text.split(":")
    try:
        numbers = [int(part) for part in parts]
    except ValueError:
        return None
    seconds = 0
    for number in numbers:
        seconds = seconds * 60 + number
    return seconds


def parse_engine_progress(text: str) -> EngineProgress | None:
    """从日志文本里取**最后一条**能认出来的进度条；认不出返回 None。"""
    found: EngineProgress | None = None
    for segment in re.split(r"[\r\n]+", text):
        match = _BAR_RE.search(segment)
        if match is None:
            continue
        total = int(match.group("total"))
        if total <= 0:
            continue
        done = int(match.group("done"))
        rate_text = match.group("rate")
        if rate_text is None or rate_text == "?":
            rate = None
        else:
            try:
                rate = float(rate_text)
            except ValueError:
                rate = None
        found = EngineProgress(
            done=done,
            total=total,
            percent=min(1.0, done / total),
            elapsed_seconds=_to_seconds(match.group("elapsed")),
            eta_seconds=_to_seconds(match.group("remaining")),
            rate=rate,
            raw=segment.strip(),
        )
    return found


def read_log_tail(path: Path, max_bytes: int = _TAIL_BYTES) -> str:
    """读日志尾部（不会把整份日志读进内存）。"""
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            raw = handle.read()
    except OSError:
        return ""
    return raw.decode("utf-8", errors="replace")


def progress_from_log(path: Path | None) -> EngineProgress | None:
    """从引擎日志文件读进度；文件不在/读不出/解析不出都返回 None。"""
    if path is None:
        return None
    text = read_log_tail(path)
    if not text:
        return None
    return parse_engine_progress(text)
