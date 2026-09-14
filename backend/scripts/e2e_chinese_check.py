"""端到端验收：中文文献（不翻译）跑通 上传 → 取字 → 导读/术语 → 问答带出处。

用 TestClient 在进程内起应用（不另开端口），数据目录与库都指向 %TEMP%，不写仓库。
引擎环境变量来自 backend/.env，所以请用 backend 的 venv、在 backend 目录下运行：

    cd docwise-web/backend
    .venv/Scripts/python.exe <本脚本> <中文 PDF 路径>
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

BACKEND = Path(__file__).resolve().parents[1]  # backend/（脚本在 backend/scripts/）
sys.path.insert(0, str(BACKEND))

TMP = Path(tempfile.gettempdir()) / f"docwise_e2e_cn_{uuid4().hex}"
TMP.mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{(TMP / 'e2e.db').as_posix()}"

from app import storage  # noqa: E402

storage.DATA_DIR = TMP
storage.UPLOADS_DIR = TMP / "uploads"
storage.OUTPUTS_DIR = TMP / "outputs"
storage.BACKUPS_DIR = TMP / "backups"
for _d in (storage.UPLOADS_DIR, storage.OUTPUTS_DIR, storage.BACKUPS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

PDF = Path(sys.argv[1])
report: dict = {"pdf": str(PDF)}


def main() -> int:
    with TestClient(app) as client:
        reg = client.post(
            "/api/auth/register", json={"username": "e2e", "password": "e2e-pass-123"}
        )
        assert reg.status_code == 201, reg.text
        token = reg.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        with PDF.open("rb") as handle:
            resp = client.post(
                "/api/tasks/upload",
                files={"file": (PDF.name, handle, "application/pdf")},
                data={"tier": "fast", "source_lang": "zh", "target_lang": "zh"},
                headers=headers,
            )
        assert resp.status_code == 202, resp.text
        task = resp.json()
        task_id = task["id"]
        keys = ("id", "status", "source_lang", "target_lang", "native")
        report["upload"] = {k: task.get(k) for k in keys}

        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            detail = client.get(f"/api/tasks/{task_id}", headers=headers).json()
            if detail["status"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(1.0)
        report["task_status"] = detail["status"]
        report["error_message"] = detail.get("error_message")
        report["translated_path"] = detail.get("translated_path")
        report["dual_translated_path"] = detail.get("dual_translated_path")
        blocks = detail.get("blocks") or []
        report["blocks"] = len(blocks)
        report["block_sample"] = [
            {
                "block_id": b["block_id"],
                "text": (b["text"] or "")[:40],
                "translated": b["translated"],
            }
            for b in blocks[:3]
        ]

        if detail["status"] != "completed":
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1

        # 导读 / 术语（真调 DeepSeek，惰性生成）
        u = client.post(f"/api/tasks/{task_id}/understanding", headers=headers)
        report["understanding_http"] = u.status_code
        uj = u.json()
        report["understanding_status"] = uj.get("status")
        report["understanding_error"] = uj.get("error")
        guide = uj.get("guide") or {}
        report["guide_keys"] = sorted(guide.keys())
        def brief(field: dict | None) -> dict:
            return {
                "text": (field or {}).get("text", "")[:50],
                "src": (field or {}).get("source_block_ids"),
            }

        report["guide_sample"] = {k: brief(v) for k, v in list(guide.items())[:2]}
        report["terms"] = len(uj.get("terms") or [])

        # 问答：答案必须带出处，且出处 block_id 必须真的存在于本任务
        a = client.post(
            f"/api/tasks/{task_id}/ask",
            json={"question": "这份文献的结论是什么？"},
            headers=headers,
        )
        report["ask_http"] = a.status_code
        aj = a.json() if a.status_code == 200 else {}
        report["answer"] = (aj.get("answer") or "")[:200]
        src = aj.get("source_block_ids") or []
        report["answer_source_ids"] = src
        known = {b["block_id"] for b in blocks}
        report["source_ids_all_exist"] = bool(src) and all(s in known for s in src)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
