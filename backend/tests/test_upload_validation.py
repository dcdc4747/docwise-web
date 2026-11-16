"""上传校验：扩展名与 Content-Type 都能伪造，必须看文件头。

背景：把一段文本改名成 .pdf 上传，接口以前返回 202 直接入队，等引擎跑起来才失败，
失败文案还是英文的 `Failed to open stream`。用户白等，worker 白跑。
"""

from fastapi.testclient import TestClient

from app.main import app


def test_upload_rejects_text_renamed_as_pdf() -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/api/tasks/upload",
            files={"file": ("note.pdf", b"hello, not a pdf", "application/pdf")},
        )
    assert resp.status_code == 400
    assert "不是有效的 PDF" in resp.json()["detail"]


def test_upload_rejects_empty_file() -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/api/tasks/upload",
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )
    assert resp.status_code == 400
    assert "不是有效的 PDF" in resp.json()["detail"]
