# docwise-web

文档翻译智能体——**Agent 是大脑，程序是手脚**。用户上传英文文献 PDF，获得"像原文档的中文版"：翻译、结构保留排版、质检一条龙。

## 阶段 0（2026-08-04 启动，DDL：2026-08-07）

目标：仓库、后端、前端、数据库可启动。

验收标准：**未参与搭建的队友，从 git clone 全新仓库开始，按本 README 操作，十分钟内跑起来看到首页**（阶段 0 验收测试员：邹州，兼任）。

## 目录结构

```text
docwise-web/
├── backend/    # FastAPI 后端（Python）
├── frontend/   # Vue3 + Naive UI 前端（由前端负责人创建）
└── README.md
```

## 后端启动（约 3 分钟）

前置：安装 [uv](https://docs.astral.sh/uv/)（Python 包与环境管理器）。Windows 可用 `pip install uv`，或按官网说明安装。

```bash
cd backend
uv sync        # 自动创建 .venv 并安装依赖（首次需联网，几分钟）
uv run uvicorn app.main:app --port 8000
```

启动后验证：

- 打开 http://127.0.0.1:8000/api/health ，返回 `{"status":"ok",...}` 即后端正常。
- 打开 http://127.0.0.1:8000/api/tasks ，返回任务列表（初始为空数组）。
- 数据库为 SQLite，首次启动自动建表，文件在 `backend/data/docwise.db`（不提交仓库）。

可选配置：复制 `backend/.env.example` 为 `backend/.env`，可修改数据库路径（.env 不提交仓库）。

## 前端启动（待前端负责人补充）

占位：Vue3 + Vite + Naive UI。启动命令与步骤由前端负责人补充到本节。

## 阶段 0 验收方式

1. `git clone` 本仓库（全新克隆，不用旧环境）。
2. 严格按"后端启动"与"前端启动"两节操作，全程计时。
3. 十分钟内看到前端首页，且后端健康检查通过，即验收通过。
4. 验收记录（截图 + 步骤 + 卡点）提交到仓库或群里。

## 约定

- API key 等密钥一律进本地 `.env`，**绝不提交仓库**。
- 提交信息使用 Conventional Commits：`feat(scope): message`。
- 数据库访问统一走 SQLAlchemy ORM，将来换 PostgreSQL 只改配置。
