# docwise-web 项目规则（AI 协作手册）

本文件是 docwise-web 的 AI 编程助手规则（Codex 会自动读取）。所有在本仓库里工作的 AI 必须遵守。

## 项目一句话

文献理解智能体——Agent 是大脑，程序是手脚。**对象是文献本身，不限于外文**：外文文献译成中文并保留原排版（纯中文 / 双语对照）；**中文文献不翻译**，直接抽文字层进理解层（结构化导读 / 术语表 / 带出处的问答），**每条结论都点得回原文那一句**。当前进度：阶段 0/1/2 已完成并验收，Web MVP 功能完成（上传 / 进度 / 预览 / 下载 / 历史 + 档位 + 账号体系 + 任务生命周期 + 诚实进度 + 同源部署 + 中文文献支持）。详见 README「开发路线」。

## 界面形态（形态 v1，2026-09-14 落地）

- **两级结构**：**L1「我的论文」库页**（空库才出大 hero；上传卡；进行中任务条；刚完成的绿色横幅；论文卡片网格）
  与 **L2 全屏阅读工作区**（工具条「← 我的论文」+ 左栏 + 右助手）。`view` 状态切换，**回 L1 不清 currentTask**（后台 SSE 继续推）。
- **L2 左栏三种渲染**（`docMode`）：**段落精读（默认）**——按块重排、跨页插页分隔条、段号按页内重算、
  原文小字灰 + 译文主文，锚点是我们自己的 DOM；**原版 / 纯中文 / 双语 PDF**——`components/PdfPane.vue`
  用 **pdf.js** 渲染（canvas + 文字层坐标），所以**点出处能滚到那一段并画高亮框、点 PDF 里的任意一段能
  「就这段提问」**（iframe 时代这两件事物理上做不到，别再改回去）。
  **鼠标扫过 / 点中的是"一整段"，不是一行**（行按几何关系并成段，阈值取自实测：段内行距 14.7、段间 ≥25.3）。
  **三种产物都能对到段**：双语稿原页直接搜到；中文文献原稿直接搜到；
  **纯中文稿靠双语稿的「原页 → 译页」几何参照对齐**（块里是英文、这一份是中文，搜不到是必然的，
  但双语稿是版式保持的交替产物，同一 y 区间就是同一段的中文）——**不用改引擎**。
  真对不上时（图/表/扫描页没有文字层）**只翻到那一页 + 如实说，绝不假高亮**。
- **L2 右助手三个副页签**：问答 ｜ 导读 ｜ 术语（页签数不再增加；新功能先问「能不能放进问答」）。
- **出处硬约定**：一律显示「第 X 页 · 第 Y 段」（`src/blockLabel.js`；段号按页内重算，**绝不裸露块编号**）；
  点出处要滚到那一段并高亮脉冲；无出处的要点置灰不可点（死链不许做成活链样式）；术语定位**命中后回填**，未命中直说。
- **提问锚点**：段落精读里划词 → 提问请求带 `focus_block_ids`（后端只收本任务真实存在的块编号）。
- **手机（<1024px）**：段落视图全宽 + 助手变底部抽屉三档（peek / 半屏 / 近全屏），点出处自动降 peek；
  **窄屏只渲染 `.ptop` 一条顶栏**（← / 文件名 / 原版·段落 / ⤓ / ⋯），桌面那条 `.reader-top` 整条不渲染——
  两条顶栏叠起来会白吃掉首屏一百多像素（照原型比对时抓出来的偏差）。
- **照原型搬的规矩（别只搬配色）**：原型是**设计权威**（与 `docs/产品形态说明.md` 冲突时以原型为准）。
  搬法是三步：① 原型 `<style>` 整段搬进 `src/style.css` 的 `.dw` 命名空间（**不许污染登录页 / 管理后台**）；
  ② 模板**照抄结构层级与类名**；③ 原型末尾那段命令式 JS 重写成 `ref` / `computed` / `watch`
  （不在 Vue 里再搞一套 `querySelector` 改 DOM）。原型里的 `.proto-bar`（屏切换导航）与 `.phone`（手机外框）
  是**原型自己的示意外壳，不属于产品界面**。旧结构类名（`reader-card` / `workbench-head` / `reader-doc` /
  `reader-assist` / `ask-panel` …）一律不许留——`frontend/tests/app.smoke.test.js` 里有黑名单，结构退化会红。
- 验收基准是**逐屏与原型截图并排比对**，不是口头说「对上了」；取图用 `frontend/tools/shoot.mjs`
  （零依赖 CDP 截图驱动，配置样例见 `frontend/tools/shoot.config.example.json`）。
- 完整形态定义见 `docs/产品形态说明.md`；可点原型见 `frontend/prototype/product-form.html`。

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
├── app/main.py       # FastAPI 入口：启动初始化（建表/补列/FTS/归属存量任务/回收磁盘）、/api/health（真检查）、CORS、挂载各路由
├── app/routers/      # tasks.py = 任务与进度（上传/列表/详情/文件/SSE/理解层 + 取消·重试·删除）；ask.py = 论文问答；auth.py = 注册/登录/退出/me/改密/票据/演示一键登录；admin.py = 管理后台
├── app/auth.py       # 账号核心逻辑：scrypt 密码哈希、会话令牌（只存 sha256、可吊销）、临时票据、登录限流
├── app/deps.py       # 依赖注入 + 守卫：get_current_user / get_user_for_files(票据) / get_user_for_events(票据) / load_owned_task / require_admin
├── app/storage.py    # 磁盘治理：uploads / outputs/{task_id} / backups 三个目录的唯一约定 + 删文件与孤儿目录回收
├── app/progress.py   # 诚实进度：解析引擎日志里的 tqdm 进度条（页进度/速率/预计剩余），解析不出返回 None（绝不编进度）
├── app/webapp.py     # 同源部署：把 frontend/dist 挂到 "/"（SPA 回退 + 入口文件不缓存 + 局域网地址提示），缺产物自动跳过
├── app/llm.py        # DeepSeek 客户端：extract_understanding（导读/术语）+ answer_question（问答）；**导读对超长文献均匀抽样、JSON 被截断时按字段抢救**
├── app/models.py     # SQLAlchemy：tasks（含 user_id 归属）、task_history、task_blocks、task_understanding、users、auth_sessions、auth_tickets
├── app/config.py     # 配置：DATABASE_URL；CORS 白名单；问答阈值；**导读输入预算与输出上限（DOCWISE_UNDERSTANDING_MAX_CHARS / _MAX_TOKENS）**；账号开关（session_days / legacy_owner / demo_autologin / 登录失败上限）
├── app/db.py         # 引擎与会话；SQLite PRAGMA（WAL+busy_timeout）；ensure_fts 建 FTS5（trigram）检索表 + 触发器
├── app/logging_setup.py # 日志：data/logs/docwise.log 轮转 + 控制台（写不了文件自动降级）
├── app/worker.py     # 单进程 worker：扫表恢复/行锁认领/线程池跑引擎/取消信号表/事件总线；心跳 + 空闲扫表兜底 + 单任务异常不杀循环
├── app/engine/       # 引擎接口（TranslationEngine + CancelToken）+ OpenSourceEngine 适配器（Popen/可取消/引擎日志）+ MediumEngine（中档）+ **NativeEngine（中文文献：不翻译，抽文字层 + 出原稿）** + registry（按"语言对 + 档位"选引擎）
├── scripts/          # 运维/工具脚本：backup_db.py（VACUUM INTO 备份 + 只留最近 N 份）、reset_password.py（重置密码/提升管理员/列账号）、**extract_blocks.py（中文文献取字：抽文字块 + 出原稿，跑在引擎 Python 里）**、**e2e_chinese_check.py（中文文献端到端验收）**
└── pyproject.toml    # uv 依赖；.env.example 模板（复制为 .env，不提交）
```

- **账号与权限**：所有任务接口都需登录（`Authorization: Bearer <令牌>`），并按归属过滤——**非本人一律 404**；进度推送 / PDF 预览 / 文件下载这三种浏览器请求带不了请求头，用 `?ticket=` 票据（绑定 用户+任务+用途，60 秒）。账号表/会话表/票据表由 `create_all` 自动建；`tasks.user_id` 由 `_ensure_schema` 补列；存量无主任务在启动时按 `DOCWISE_LEGACY_OWNER` 归属。
- **任务流转**：POST /api/tasks/upload 只建任务立即返回 202（status=pending），worker 后台处理（in_progress→completed/failed/cancelled），SSE 推送进度（前端也可轮询 GET /api/tasks/{id} 兜底）。
- **任务生命周期（E 批）**：`POST /api/tasks/{id}/cancel`（跑着的终止引擎子进程、排队中的直接置终态）、`POST /api/tasks/{id}/retry`（仅 failed/cancelled）、`DELETE /api/tasks/{id}`（连子表与磁盘产物一起删）。**结果文件统一落 `data/outputs/{task_id}/`**，删除任务/重试会自动清理；启动时回收孤儿目录。**SQLite 外键没开级联，删任务必须手工删子表**（`routers/tasks.py` 的 `_purge_task_children`）。
- **诚实进度（F 批）**：进度不是编的，是**解析引擎自己打在 `data/outputs/{id}/engine.log` 里的 tqdm 进度条**（`2/10 [00:01<00:05, 1.44it/s]`，单位是页）：`app/progress.py` 负责解析（tqdm 用 `\r` 重绘，必须按 `[\r\n]+` 切；**解析不出就返回 None，界面显示"引擎还没报进度"，绝不编百分比**），worker 每 1.5s 搬进 `tasks.progress/eta_seconds/stage` 并推 SSE（**只增不减**），任务详情另有当场解析的 `engine_progress`、`elapsed_seconds`（由 `started_at`/`finished_at` 算）与 `queue_position`（排队时"前面还有几篇"）。
- 启动后端：`cd backend && uv sync && uv run uvicorn app.main:app --port 8000`（单进程 worker，勿用 `--workers N` 并发，避免 SQLite 写锁）。
- **同源部署（推荐演示与手机真机用）**：先 `cd frontend && bun install && bun run build`，再 `cd backend && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000` —— **一个地址同时给页面与接口**，手机访问 `http://<电脑局域网IP>:8000/`（启动日志会直接列出本机内网地址），不用拼 `?apiBase=`、也不用配 CORS。实现见 `app/webapp.py`：**挂载调用必须写在 `main.py` 最后**（Starlette 按注册顺序匹配，写在前面会把 `/api/...` 吃成静态文件）；`/api`、`/files` 下的未知路径**不参与** SPA 回退（保持 JSON 404），只有 `Accept: text/html` 的浏览器导航才回退 `index.html`；`index.html` / `sw.js` / `manifest.webmanifest` 发 `Cache-Control: no-cache`（防装了 PWA 的手机吃旧壳）；产物不存在只跳过挂载 + 打一条日志（开发态不构建也能起服务），`DOCWISE_SERVE_FRONTEND=0` 关闭、`DOCWISE_FRONTEND_DIST=<路径>` 改位置（相对路径按仓库根解析）。**改完前端要重新构建**，后端只负责端出去、不会替你编译。
- > 翻译引擎（OpenSourceEngine）通过子进程调用，需配置环境变量 `DOCWISE_ENGINE_PYTHON` / `DOCWISE_ENGINE_SCRIPT` / `DOCWISE_ENGINE_SERVICE` 才会运行；未配置则返回错误。**中档引擎（MediumEngine）用独立的前缀 `DOCWISE_ENGINE_MEDIUM_PYTHON` / `DOCWISE_ENGINE_MEDIUM_SCRIPT` / `DOCWISE_ENGINE_MEDIUM_SERVICE`，未配则回退到基础变量。** 这些（及 `DEEPSEEK_*`）写入 `backend/.env` 后，后端启动时自动注入环境（`_inject_engine_env`），无需手动 `$env:`。
- > **中文文献不翻译**（对象是文献本身，不限于外文）：上传时 `source_lang=zh&target_lang=zh` → `is_native_pair` 命中 → 走 `NativeEngine`，子进程跑仓库自带的 `scripts/extract_blocks.py`（需要 PyMuPDF，用 `DOCWISE_ENGINE_NATIVE_PYTHON`，未配回退 `DOCWISE_ENGINE_PYTHON`）抽文字块，产物 `mono`＝原稿副本、`dual`＝null、每块 `translated`＝null；理解层靠 `translated or text` 照常工作。**`zh → en` 是翻译任务，不走这条路。** 扫描件（无文字层）如实失败。
- **代码架构图**：完整的分层 / 模块依赖 / 数据流 / 接入点 / 注意事项见 `docs/代码架构图.md`。**改动代码（尤其模块 / 接口 / 数据结构 / 路由 / 引擎层）后，请同步更新该图**，方便后续 AI 快速理解底层。

## 测试与验收

- 改完代码必须验证：后端 `pytest tests/ -q` 全过 + `ruff check app tests` 通过；`/api/health` 正常。
- 测试约定：功能测试默认"已登录"（conftest 覆盖鉴权依赖，账号 id 见 `tests/helpers.py`）；**直接建任务要带 `user_id=TEST_USER_ID`**；鉴权本身由 `test_auth` / `test_authz` / `test_admin` 用真实令牌覆盖（未登录 401、跨用户 404、后台 403）。
- 任务生命周期测试见 `test_task_lifecycle.py`（删除/重试/取消/归属/文件清理）；`test_engine_cancel.py` **真起子进程**验证"取消能把引擎杀掉"，所以**别 mock 掉 Popen**。测试里不要用 `tmp_path`／`mkdtemp` 建目录（受限环境不可写），用 `storage` 那几个模块级目录（conftest 已指向临时目录）。
- 诚实进度的测试见 `test_progress.py`：解析样本取自**真实 engine.log**；其中一个用例让假引擎往 `engine.log` 写 tqdm 进度，并断言"进度在引擎还在跑的时候就落库了"（不是等结束才一次性写）。
- 同源部署的测试见 `test_same_origin.py`：断言 `/api`、`/files` 下的未知路径仍是 **JSON 404**（没被 SPA 回退成 HTML）、只有 `Accept: text/html` 才回退壳、入口文件带 `no-cache`、**产物缺失时不挂载也不报错**，以及一条结构性断言"挂载点之后不许再有 `/api`、`/files` 路由"（防有人把路由写回 `main.py` 末尾挂载之后）。
- 前端 `bun dev` 能跑、页面正常；界面改动请在 PR 里贴截图。
- **前端渲染检查（必须有）**：`cd frontend && bun run test`（vitest + happy-dom，62 个用例：progressText 17 + blockLabel 12 + pdfText 13 + App.vue 渲染冒烟 20）。加这个是因为真出过事故——模板里把函数当值插值（少写一对括号），Vue 会 `String(fn)` 把**整个函数源码印在页面上**，而 `vite build` 一声不吭，最后是用户截图发现的。所以：
  - `tests/app.smoke.test.js` 会真的挂载 `App.vue`、走一遍"打开一篇正在翻译的论文"，断言页面文本**不含任何源码痕迹**（`function `、`=>`、`{{` 等），并断言进度区显示的是人话；**同时直接锁原型的结构类名、断言旧结构类名一个都不出现**（`FORBIDDEN_LEGACY`），以及 PDF 模式"对不上时只翻页、不假高亮"；
  - `tests/pdfText.test.js` 单测 PDF 文字层的行合并 / 归一化 / 按文本找位置（**命中算错不会崩，只会把高亮打到不相干的地方**，最需要单测）；
  - `tests/progressText.test.js` 单测进度文案逻辑（`src/progressText.js`）；
  - **模板里要渲染的值一律用 `computed` 或 `ref`**（别用普通函数），这样"少写括号"也不会出事；
  - 新增界面功能请顺手补一个用例，别让这类问题再靠用户的眼睛来发现。
- 各阶段验收标准见 README「开发路线」与对应 issue。

## 沟通

- 卡住或需要权限时找仓库管理员 dcdc4747，不要私自绕过保护规则。
- 涉及公共接口、数据库结构的大改动，先在 PR 或群里说明再动手。
