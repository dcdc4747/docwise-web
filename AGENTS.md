# docwise-web 项目规则（AI 协作手册）

本文件是 docwise-web 的 AI 编程助手规则（Codex 会自动读取）。所有在本仓库里工作的 AI 必须遵守。

## 项目一句话

文档翻译智能体——Agent 是大脑，程序是手脚。用户上传英文材料，获得"像原文档的中文版"（纯中文/双语对照）。当前进度：**阶段 1（最小翻译链路）已完成并验收；阶段 2（Web 端闭环 MVP）进行中**——在翻译链路上做 Web 界面（上传/进度/预览/下载/历史）+ 档位选择。详见 README「开发路线」。

## 分工与身份（开工先确认你是谁）

**开工第一步：运行 `git config user.name`（必要时再看 `git config user.email`）确认当前使用者的 GitHub 身份，然后对照下面的分工表，确定当前用户负责的模块。**

分工表（2026-08-04 定稿）：

| GitHub 用户名 | 称呼 | 负责模块 |
|---|---|---|
| dcdc4747 | 邹州 | 项目负责人 / 后端 / 仓库管理 / README / 密钥安全 / 验收（阶段 0 兼任） |
| eternal-pudding | 小时 | 前端负责人（Vue3 + Naive UI 首页） |
| Niluf-06 | 小符 | 视觉三方快测（对比表、结论） |
| King-Rosamist | 小徐 | 测试样本与素材准备（协作者邀请已发出） |
| cshi0827 | 小陈 | 阶段 0 暂不参与，后续再安排 |

职责边界：

- 只做当前用户负责模块内的工作；需要改动其他模块时，先向用户说明，建议由对应负责人处理，不要擅自改别人的模块。
- 如果通过 git 身份无法确定当前用户是谁（或身份对不上分工表），停下来问用户："你的 GitHub 用户名是什么？负责哪块？"
- AI 负责把任务推进到 PR 创建完成，不越权合并（合并只能由 dcdc4747 审批后执行）。

## Git 协作流程（必须遵守）

1. 开工前先同步：`git checkout main` 然后 `git pull`。
2. 每个任务建独立分支，命名：`feat/xxx`（功能）、`fix/xxx`（修复）、`docs/xxx`（文档）、`chore/xxx`（杂项）。**禁止直接在 main 上改代码**。
3. 提交信息用 Conventional Commits：`feat(scope): 说明`，scope 如 frontend / backend / repo。
4. **AI 必须主动把任务推进到 PR 创建完成**：push 到自己的分支（`git push -u origin <分支名>`），然后创建 Pull Request（`gh pr create` 或指导用户网页操作）。PR 描述必须写清：做了什么、怎么验证、相关截图。**不要只做本地提交不推送——PR 是进入 main 的唯一入口。**
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

## 后端结构（当前）

```text
backend/
├── app/main.py       # FastAPI：/api/health、/api/tasks、/api/tasks/{id}、POST /api/tasks（异步任务）
├── app/models.py     # SQLAlchemy：tasks（任务卡）、task_history、task_blocks（每块状态）
├── app/config.py     # 配置：DATABASE_URL 读 .env
├── app/db.py         # 引擎与会话
├── app/engine/       # 翻译引擎接口（TranslationEngine）+ OpenSourceEngine 适配器 + registry（按档位选引擎）
└── pyproject.toml    # uv 依赖；.env.example 模板（复制为 .env，不提交）
```

启动后端：`cd backend && uv sync && uv run uvicorn app.main:app --port 8000`
> 翻译引擎（OpenSourceEngine）通过子进程调用，需配置环境变量 `DOCWISE_ENGINE_PYTHON` / `DOCWISE_ENGINE_SCRIPT` / `DOCWISE_ENGINE_SERVICE` 才会运行；未配置则返回错误。

## 测试与验收

- 改完代码必须验证：后端 `pytest tests/ -q` 全过 + `ruff check app tests` 通过；`/api/health` 正常。
- 前端 `bun dev` 能跑、页面正常；界面改动请在 PR 里贴截图。
- 各阶段验收标准见 README「开发路线」与对应 issue。

## 沟通

- 卡住或需要权限时找邹州（dcdc4747），不要私自绕过保护规则。
- 涉及公共接口、数据库结构的大改动，先在 PR 或群里说明再动手。
