# 贡献指南

## 先跑起来

需要三个运行时：Python 3.12（用 [uv](https://docs.astral.sh/uv/) 管理）、[bun](https://bun.sh/)、以及仓库内置引擎自己的虚拟环境。

```bash
uv sync --project engine      # 引擎（重依赖，独立环境）
cd backend && uv sync         # 后端
cd ../frontend && bun install # 前端
```

启动：`cd backend && uv run uvicorn app.main:app --port 8000`，另开一个终端 `cd frontend && bun dev`。
第一次翻译会联网下载一次版面模型，之后走本地缓存。

## 提 PR 之前必须做的四件事

```bash
# 1) 后端：ruff 查的是整个 backend，含 scripts/（只查 app tests 会漏）
cd backend && uv run ruff check . && uv run pytest -q

# 2) 契约闸：代码里的路由必须与 backend/.contract/api.json 一致
cd backend && uv run python scripts/check_contract.py

# 3) 前端：渲染冒烟 + 构建
cd frontend && bun run test && bun run build

# 4) 界面改动在 PR 里贴截图
```

## 分支与提交

- **一个任务一条分支，从最新 main 拉**；前缀 `feat/` `fix/` `docs/` `chore/` `refactor/`。
- 提交信息用 Conventional Commits：`feat(scope): 一句话说清做了什么`。
- 不要把 PR 堆在别人还没合的分支上；**不要对已开 PR 的分支 force-push**（那条 PR 会被平台冻住）。
- 合进 main 需要 review；CI 两个 job 都要绿。

## 三条不能碰的边界

- **`backend/data/` 里的真实数据一个字节都不能动**。要改走脚本：默认只预览，`--apply` 才写，必须幂等。
- **`backend/app/blocktypes.py` 是块类型的唯一权威**，别在别处再写一套判级。
- **后端运行时只允许 6 个包**（`fastapi` / `python-multipart` / `uvicorn[standard]` / `sqlalchemy` / `pydantic-settings` / `httpx`）。
  重依赖放独立环境、用子进程调 —— `engine/` 就是这么做的。

## 契约优先

接口、数据模型、前端命名三份契约在 `docs/contracts/`。**实现与契约不一致时，以契约为准改代码**；
确属契约写错，先改契约再改代码（同一条 PR 里都行）。

## 公开口径

提交前扫一遍改动（含注释、文档字符串、提交信息）：

- 不出现密钥、账号、真实姓名、学校/单位信息、本机绝对路径；
- 不出现特定活动的字眼（参赛、评审等），一律用中性描述；
- 扫描中文路径要用 `git ls-files -z`：普通输出会把中文转义，按它拼路径会**静默跳过**，扫出"干净"的假象。

## 目录约定

- 现行文档放 `docs/` 根下（`ARCHITECTURE.md` / `PRODUCT.md` / `AGENT.md`）；过程记录进 `docs/records/`；
  接口与数据结构契约进 `docs/contracts/`。详见 [docs/README.md](docs/README.md)。
- 改了模块 / 接口 / 数据结构 / 路由 / 引擎层，**必须同步更新 `docs/ARCHITECTURE.md`**。
