# docwise-web 项目规则（AI 协作手册）

本文件是 docwise-web 的 AI 编程助手规则（Codex 会自动读取）。所有在本仓库里工作的 AI 必须遵守。

## 项目一句话

文档翻译智能体——Agent 是大脑，程序是手脚。当前阶段 0：项目骨架（后端 FastAPI + SQLAlchemy + SQLite，前端 Vue3 + Naive UI 由前端负责人搭建）。

## Git 协作流程（必须遵守）

1. 开工前先同步：`git checkout main` 然后 `git pull`。
2. 每个任务建独立分支，命名：`feat/xxx`（功能）、`fix/xxx`（修复）、`docs/xxx`（文档）、`chore/xxx`（杂项）。**禁止直接在 main 上改代码**。
3. 提交信息用 Conventional Commits：`feat(scope): 说明`，scope 如 frontend / backend / repo。
4. 改动完成后 push 到自己的分支，然后开 Pull Request（`gh pr create` 或网页操作）。PR 描述必须写清：做了什么、怎么验证、相关截图。
5. **不要直接推 main**——main 分支有保护，必须由 dcdc4747（邹州）审批后才能合并。
6. 如果 PR 被要求修改：在同一个分支继续改、commit、push，PR 会自动更新。
7. 遇到合并冲突：先 `git pull origin main` 到自己的分支，解决冲突后 add + commit + push。
8. 合并统一用 Squash and merge（由负责人操作），合并后删除功能分支。

## 安全（最高优先级）

- 绝不提交 `.env`、API key、token、密码。`.gitignore` 已排除 `.env` 和本地数据库文件。
- 每次提交前检查 `git diff --staged` 是否混入密钥。
- 大文件（样本 PDF、录屏、对比表）**不走 git**，放共享网盘/群里。

## 技术约定

- Python：用 `uv` 管理虚拟环境和依赖（backend 已配 `pyproject.toml` + `uv.lock`）。
- JavaScript/TypeScript：优先用 `bun`；前端技术栈 Vue3 + Naive UI（Vite 脚手架）。
- Python 代码风格：`pathlib` 优先于 `os.path`；f-string 优先于 `.format()`/`%`；函数签名写类型注解；不要给没改过的代码加注释或文档字符串。
- 数据库：统一走 SQLAlchemy ORM，SQLite 起步，将来换 PostgreSQL 只改配置。

## 后端结构（阶段 0）

```text
backend/
├── app/main.py     # FastAPI 入口：/api/health 健康检查、/api/tasks 任务列表
├── app/models.py   # SQLAlchemy 模型：tasks（任务卡）、task_history（历史记录）
├── app/config.py   # 配置：DATABASE_URL 读 .env
├── app/db.py       # 引擎与会话
├── pyproject.toml  # uv 依赖
└── .env.example    # 环境变量模板（复制为 .env 使用，不提交）
```

启动后端：`cd backend && uv sync && uv run uvicorn app.main:app --port 8000`

## 测试与验收

- 改完代码必须验证能跑：后端启动后 `/api/health` 返回 `{"status":"ok",...}`。
- 阶段 0 验收标准：未参与搭建的人按 README 十分钟内跑起来看到首页。

## 沟通

- 卡住或需要权限时找邹州（dcdc4747），不要私自绕过保护规则。
- 涉及公共接口、数据库结构的大改动，先在 PR 或群里说明再动手。
