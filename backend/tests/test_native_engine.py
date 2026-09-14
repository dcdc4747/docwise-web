"""中文文献（不需要翻译）链路测试。

产品口径：对象是**文献本身**，不限于外文文献。中文文献不该被塞进翻译引擎——
它只需要"抽文字层 → 进理解层（导读/术语/问答/出处）"，产物就是原稿本身。

这里覆盖四件事：
1. 语言对选引擎：只有"源=目标=中文"才走取字引擎；zh→en 仍是**翻译**任务；
2. NativeEngine 真起子进程（用假取字脚本），验证块、产物、以及 `translated=None`；
3. 扫描件（无文字层）失败要说人话，不能假装成功；
4. 上传接口的语言校验与落库。

真脚本 `scripts/extract_blocks.py` 需要 PyMuPDF（跑在引擎环境里），所以这里对它做
"存在 + 可编译 + 纯函数单测"，端到端实测另见 PR 说明。
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from helpers import TEST_USER_ID, upload_pdf

from app.db import SessionLocal
from app.engine import TaskState, Tier, TranslateRequest, get_engine
from app.engine.native import BUNDLED_EXTRACTOR, NativeEngine
from app.main import app
from app.models import Task

FAKE_EXTRACTOR = """
import json, shutil, sys
from pathlib import Path
args = sys.argv[1:]
src = Path(args[args.index("--input") + 1])
out = Path(args[args.index("--output") + 1])
out.mkdir(parents=True, exist_ok=True)
mono = out / f"{src.stem}_mono.pdf"
shutil.copyfile(src, mono)
blocks = [
    {"block_id": "p1_b0", "text": "这是一份中文文献的摘要。", "translated": None},
    {"block_id": "p1_b1", "text": "第二段讲研究方法。", "translated": None},
]
(out / "result.json").write_text(
    json.dumps(
        {"status": "completed", "mono": str(mono), "dual": None,
         "blocks": blocks, "error": None},
        ensure_ascii=False,
    ),
    encoding="utf-8",
)
print("取字完成", flush=True)
"""

FAKE_SCAN_EXTRACTOR = """
import json, sys
from pathlib import Path
args = sys.argv[1:]
out = Path(args[args.index("--output") + 1])
out.mkdir(parents=True, exist_ok=True)
(out / "result.json").write_text(
    json.dumps(
        {"status": "failed",
         "error": "这份 PDF 没有可抽取的文字层（可能是扫描件或纯图片版）",
         "blocks": []},
        ensure_ascii=False,
    ),
    encoding="utf-8",
)
"""


def _workdir() -> Path:
    """系统临时目录下的工作目录（不用 tmp_path/mkdtemp：受限环境里不可写）。"""
    path = Path(tempfile.gettempdir()) / f"docwise_native_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _native_env(monkeypatch, script: Path) -> None:
    monkeypatch.setenv("DOCWISE_ENGINE_NATIVE_PYTHON", sys.executable)
    monkeypatch.setenv("DOCWISE_ENGINE_NATIVE_SCRIPT", str(script))


def test_native_engine_only_for_chinese_to_chinese() -> None:
    """只有"源=目标=中文"才不翻译；zh→en 是翻译任务，不能误判。"""
    assert get_engine(Tier.FAST, "zh", "zh").name == "native-engine"
    assert get_engine("fast", " ZH ", "zh").name == "native-engine"
    assert get_engine(Tier.FAST, "zh", "en").name == "open-source"
    assert get_engine(Tier.FAST, "en", "zh").name == "open-source"
    assert get_engine(Tier.MEDIUM, "zh", "zh").name == "native-engine"
    # 不传语言：保持原行为（按档位取翻译引擎）
    assert get_engine(Tier.FAST).name == "open-source"
    assert get_engine(Tier.MEDIUM).name == "medium-engine"


def test_native_engine_extracts_blocks_without_translation(monkeypatch) -> None:
    workdir = _workdir()
    script = workdir / "fake_extract.py"
    script.write_text(FAKE_EXTRACTOR, encoding="utf-8")
    _native_env(monkeypatch, script)

    pdf = workdir / "cn.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    result = NativeEngine().translate(
        TranslateRequest(
            source_path=pdf,
            source_lang="zh",
            target_lang="zh",
            output_dir=workdir / "out",
        )
    )

    assert result.status == TaskState.COMPLETED
    assert [b.block_id for b in result.blocks] == ["p1_b0", "p1_b1"]
    assert [b.text for b in result.blocks][0].startswith("这是一份中文文献")
    # 关键：中文文献没有译文，translated 必须是 None（前端据此只显示原文）
    assert all(b.translated is None for b in result.blocks)
    assert result.translated_path is not None and result.translated_path.exists()
    assert result.dual_path is None


def test_native_engine_says_scan_not_supported(monkeypatch) -> None:
    workdir = _workdir()
    script = workdir / "fake_scan.py"
    script.write_text(FAKE_SCAN_EXTRACTOR, encoding="utf-8")
    _native_env(monkeypatch, script)

    pdf = workdir / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    result = NativeEngine().translate(
        TranslateRequest(
            source_path=pdf,
            source_lang="zh",
            target_lang="zh",
            output_dir=workdir / "out",
        )
    )

    assert result.status == TaskState.FAILED
    assert "扫描件" in (result.error or "")


def test_native_engine_without_python_reports_clearly(monkeypatch) -> None:
    """引擎 Python 没配时要说清是配置问题，而不是"引擎未返回 result.json"。"""
    monkeypatch.delenv("DOCWISE_ENGINE_NATIVE_PYTHON", raising=False)
    monkeypatch.delenv("DOCWISE_ENGINE_PYTHON", raising=False)

    result = NativeEngine().translate(
        TranslateRequest(
            source_path=Path("nowhere.pdf"), source_lang="zh", target_lang="zh"
        )
    )

    assert result.status == TaskState.FAILED
    assert "DOCWISE_ENGINE_NATIVE_PYTHON" in (result.error or "")


def test_bundled_extractor_exists_and_compiles() -> None:
    """真脚本跑在引擎环境（另一个解释器）里，pytest 覆盖不到它，至少保证能编译。"""
    assert BUNDLED_EXTRACTOR.exists(), f"取字脚本不见了：{BUNDLED_EXTRACTOR}"
    source = BUNDLED_EXTRACTOR.read_text(encoding="utf-8")
    compile(source, str(BUNDLED_EXTRACTOR), "exec")


def _load_extractor():
    spec = importlib.util.spec_from_file_location("extract_blocks", BUNDLED_EXTRACTOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extractor_line_joining() -> None:
    """拼行规则：中文行直接接上、英文行补空格、英文连字符断行接回。"""
    module = _load_extractor()
    assert module._block_text("这是中文的\n换行不加空格") == "这是中文的换行不加空格"
    assert module._block_text("hello\nworld") == "hello world"
    assert module._block_text("trans-\nlation") == "translation"
    assert module._block_text("  前后留白  ") == "前后留白"


def test_upload_chinese_document_records_language_pair(monkeypatch) -> None:
    """上传中文文献：语言对要落库，且任务照常完成（用假引擎，不跑真取字）。"""

    class FakeNative:
        name = "native-engine"

        def translate(self, request, cancel=None):
            from app.engine import BlockState, BlockStatus, TranslationResult

            return TranslationResult(
                task_id="native",
                translated_path=None,
                blocks=[
                    BlockStatus(
                        block_id="p1_b0",
                        text="中文文献正文",
                        status=BlockState.SUCCESS,
                        translated=None,
                    )
                ],
                status=TaskState.COMPLETED,
                progress=1.0,
            )

    monkeypatch.setattr("app.worker.get_engine", lambda *a, **kw: FakeNative())

    pdf = Path(tempfile.gettempdir()) / f"docwise_cn_{uuid4().hex}.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    try:
        with TestClient(app) as client:
            task = upload_pdf(client, pdf, source_lang="zh", target_lang="zh")
            assert task["source_lang"] == "zh"
            assert task["target_lang"] == "zh"
            with SessionLocal() as session:
                row = session.get(Task, task["id"])
                assert row is not None and row.source_lang == "zh"
    finally:
        pdf.unlink(missing_ok=True)


def test_upload_rejects_unsupported_language() -> None:
    pdf = Path(tempfile.gettempdir()) / f"docwise_lang_{uuid4().hex}.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    try:
        with TestClient(app) as client:
            with pdf.open("rb") as handle:
                resp = client.post(
                    "/api/tasks/upload",
                    files={"file": (pdf.name, handle, "application/pdf")},
                    data={"tier": "fast", "source_lang": "fr", "target_lang": "zh"},
                )
        assert resp.status_code == 400
        assert "暂不支持的语言对" in resp.json()["detail"]
    finally:
        pdf.unlink(missing_ok=True)


def test_task_model_keeps_user_for_native_tasks() -> None:
    """中文文献任务同样要有主人（归属过滤不能被绕过）。"""
    with SessionLocal() as session:
        task = Task(
            user_id=TEST_USER_ID,
            filename="cn.pdf",
            original_path="/tmp/cn.pdf",
            source_lang="zh",
            target_lang="zh",
            status=TaskState.PENDING.value,
        )
        session.add(task)
        session.commit()
        assert task.id is not None
