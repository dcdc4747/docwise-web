# docwise-web 项目规则（AI 协作手册）

本文件是 docwise-web 的 AI 编程助手规则（Codex 会自动读取）。所有在本仓库里工作的 AI 必须遵守。

## 项目一句话

文档翻译智能体——Agent 是大脑，程序是手脚。用户上传英文材料，获得"像原文档的中文版"（纯中文/双语对照）。当前进度：**阶段 1（最小翻译链路）已完成并验收；阶段 2（Web 端闭环 MVP）进行中**——在翻译链路上做 Web 界面（上传/进度/预览/下载/历史）+ 档位选择。详见 README「开发路线」。

## 分工与协作（按任务，不固定模块归属）

**本仓库不固定"谁负责哪个模块"。** 团队按「领取任务制」协作：每个协作者在**当前任务卡 / issue / PR 分派的范围**内工作，任务随阶段与认领情况变动，本文档不写死分工。

开工第一步：运行 `git config user.name`（必要时再看 `git config user.email`）确认当前使用者的 GitHub 身份，以此确定向谁汇报、不越权。

协作边界：

- 每个任务以**当前任务卡 / issue / PR 描述的范围**为准，只做派给你的部分。
- 如需改动其他模块，先在 PR 或群里说明，由负责该任务的协作者处理，不要擅自改别人的模块。
- 如果通过 git 身份无法确定当前用户是谁，或不清楚本任务范围，停下来问用户："你这次任务负责哪块？"
- AI 负责把任务推进到 PR 创建完成，不越权合并（合并需仓库管理员审批后执行）。

## Git 协作流程（必须遵守）

1. 开工前先同步：`git checkout main` 然后 `git pull`。
2. 每个任务建独立分支，命名：`feat/xxx`（功能）、`fix/xxx`（修复）、`docs/xxx`（文档）、`chore/xxx`（杂项）。**禁止直接在 main 上改代码**。
3. 提交信息用 Conventional Commits：`feat(scope): 说明`，scope 如 frontend / backend / repo。
4. **AI 必须主动把任务推进到 PR 创建完成**：push 到自己的分支（`git push -u origin <分支名>`），然后创建 Pull Request（`gh pr create` 或指导用户网页操作）。PR 描述必须写清：做了什么、怎么验证、相关截图。**不要只做本地提交不推送——PR 是进入 main 的唯一入口。**
5. **不要直接推 main**——main 分支有保护，必须由仓库管理员 dcdc4747 审批后才能合并。
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

## 后端结构（当前）

```text
backend/
├── app/main.py       # FastAPI：/api/health、/api/tasks、/api/tasks/{id}、POST /api/tasks（异步）、GET /api/tasks/{id}/events（SSE 实时进度）
├── app/models.py     # SQLAlchemy：tasks（任务卡，含 source_lang/target_lang/tier/translated_path）、task_history、task_blocks（每块状态）
├── app/config.py     # 配置：DATABASE_URL 读 .env
├── app/db.py         # 引擎与会话
├── app/worker.py     # 单进程 worker：启动扫表恢复（in_progress→pending）+ 行锁认领 + 线程池跑引擎 + 事件总线（供 SSE）
├── app/engine/       # 翻译引擎接口（TranslationEngine）+ OpenSourceEngine 适配器 + registry（按档位选引擎）
└── pyproject.toml    # uv 依赖；.env.example 模板（复制为 .env，不提交）
```

- **任务流转**：POST /api/tasks 只建任务立即返回 202（status=pending），worker 后台处理（in_progress→completed/failed），SSE 推送进度（前端也可轮询 GET /api/tasks/{id} 兜底）。**更新了旧"同步卡几十秒"的路径。**
- 启动后端：`cd backend && uv sync && uv run uvicorn app.main:app --port 8000`（单进程 worker，勿用 `--workers N` 并发，避免 SQLite 写锁）。
- > 翻译引擎（OpenSourceEngine）通过子进程调用，需配置环境变量 `DOCWISE_ENGINE_PYTHON` / `DOCWISE_ENGINE_SCRIPT` / `DOCWISE_ENGINE_SERVICE` 才会运行；未配置则返回错误。**中档引擎（MediumEngine）用独立的前缀 `DOCWISE_ENGINE_MEDIUM_PYTHON` / `DOCWISE_ENGINE_MEDIUM_SCRIPT` / `DOCWISE_ENGINE_MEDIUM_SERVICE`，未配则回退到基础变量。** 这些（及 `DEEPSEEK_*`）写入 `backend/.env` 后，后端启动时自动注入环境（`_inject_engine_env`），无需手动 `$env:`。

## 测试与验收

- 改完代码必须验证：后端 `pytest tests/ -q` 全过 + `ruff check app tests` 通过；`/api/health` 正常。
- 前端 `bun dev` 能跑、页面正常；界面改动请在 PR 里贴截图。
- 各阶段验收标准见 README「开发路线」与对应 issue。

## 沟通

- 卡住或需要权限时找仓库管理员 dcdc4747，不要私自绕过保护规则。
- 涉及公共接口、数据库结构的大改动，先在 PR 或群里说明再动手。
