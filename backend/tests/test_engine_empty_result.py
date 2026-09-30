"""引擎"报完成却一个文字块都没有"必须如实失败（2026-09-30 真事故的回归）。

事故现场：把一份 8 页**扫描版** PDF 当外文文献上传（en→zh 中档）。引擎把 8 页全"翻"完、
mono/dual 都写出来了、tqdm 也跑到 100%，但 `result.json` 里 `blocks` 是空的
（扫描件没有文字层，引擎不会 OCR），而 `status` 照样写 "completed"。
后端只看 status 就落库 → 任务变成"翻译完成"，用户点进去一个字都读不到，
提问还被回一句"网络或服务繁忙"——把我们的问题说成了用户的网不好。

这里锁两件事：

1. 翻译引擎：`completed` + 0 块 = **失败**，错误里要说清"没有可抽取的文字层"，
   且不许把那份空产物端给用户；
2. 取字引擎（继承同一套解析）：同样不许把空的完成当成功；
3. 反向对照：真有块的正常结果不能被误判成失败。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from app.engine import TaskState, TranslateRequest
from app.engine.native import NativeEngine
from app.engine.open_source import OpenSourceEngine

FAKE_ENGINE_TEMPLATE = """
import json, sys
from pathlib import Path
args = sys.argv[1:]
out = Path(args[args.index("--output") + 1])
out.mkdir(parents=True, exist_ok=True)
mono = out / "fake-mono.pdf"
dual = out / "fake-dual.pdf"
mono.write_bytes(b"%PDF-1.4 fake")
dual.write_bytes(b"%PDF-1.4 fake")
blocks = __BLOCKS__
(out / "result.json").write_text(
    json.dumps(
        {"status": "completed", "mono": str(mono), "dual": str(dual),
         "blocks": blocks, "error": None, "mode": "ocr"},
        ensure_ascii=False,
    ),
    encoding="utf-8",
)
print("引擎结束", flush=True)
"""

# 注意别用 % 格式化：模板里有 %PDF-1.4，%P 会被当成格式符直接抛 ValueError
FAKE_ENGINE_EMPTY = FAKE_ENGINE_TEMPLATE.replace("__BLOCKS__", "[]")
FAKE_ENGINE_WITH_BLOCKS = FAKE_ENGINE_TEMPLATE.replace(
    "__BLOCKS__",
    '[{"block_id": "p0_b0", "text": "Abstract", "translated": "摘要"}]',
)


def _workdir() -> Path:
    """系统临时目录下的工作目录（不用 tmp_path/mkdtemp：受限环境里不可写）。"""
    path = Path(tempfile.gettempdir()) / f"docwise_empty_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _fake_pdf(workdir: Path) -> Path:
    pdf = workdir / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    return pdf


def _request(workdir: Path, pdf: Path) -> TranslateRequest:
    return TranslateRequest(
        source_path=pdf,
        source_lang="en",
        target_lang="zh",
        output_dir=workdir / "out",
    )


def test_translation_engine_empty_blocks_is_failure(monkeypatch) -> None:
    """引擎报 completed 但一个块都没有 → 失败，并说清是"没有文字层"。"""
    workdir = _workdir()
    script = workdir / "fake_empty.py"
    script.write_text(FAKE_ENGINE_EMPTY, encoding="utf-8")
    monkeypatch.setenv("DOCWISE_ENGINE_PYTHON", sys.executable)
    monkeypatch.setenv("DOCWISE_ENGINE_SCRIPT", str(script))
    monkeypatch.setenv("DOCWISE_ENGINE_SERVICE", "fake")

    pdf = _fake_pdf(workdir)
    result = OpenSourceEngine().translate(_request(workdir, pdf))

    assert result.status == TaskState.FAILED
    assert result.blocks == []
    assert "文字层" in (result.error or "")
    # 失败就不该把那份"什么都没翻出来"的产物端给用户
    assert result.translated_path is None
    assert result.dual_path is None


def test_native_engine_empty_blocks_is_failure(monkeypatch) -> None:
    """取字引擎走同一套解析：空的"完成"同样必须失败。"""
    workdir = _workdir()
    script = workdir / "fake_empty_native.py"
    script.write_text(FAKE_ENGINE_EMPTY, encoding="utf-8")
    monkeypatch.setenv("DOCWISE_ENGINE_NATIVE_PYTHON", sys.executable)
    monkeypatch.setenv("DOCWISE_ENGINE_NATIVE_SCRIPT", str(script))

    pdf = _fake_pdf(workdir)
    result = NativeEngine().translate(_request(workdir, pdf))

    assert result.status == TaskState.FAILED
    assert result.blocks == []
    assert "文字层" in (result.error or "")


def test_non_empty_result_still_completes(monkeypatch) -> None:
    """反向对照：真有块的正常结果不能被误判成失败。"""
    workdir = _workdir()
    script = workdir / "fake_ok.py"
    script.write_text(FAKE_ENGINE_WITH_BLOCKS, encoding="utf-8")
    monkeypatch.setenv("DOCWISE_ENGINE_PYTHON", sys.executable)
    monkeypatch.setenv("DOCWISE_ENGINE_SCRIPT", str(script))
    monkeypatch.setenv("DOCWISE_ENGINE_SERVICE", "fake")

    pdf = _fake_pdf(workdir)
    result = OpenSourceEngine().translate(_request(workdir, pdf))

    assert result.status == TaskState.COMPLETED
    assert [b.block_id for b in result.blocks] == ["p0_b0"]
    # 取字方式要跟着回来（界面据此如实说明"字是 OCR 认的"）
    assert result.mode == "ocr"
    assert result.translated_path is not None
