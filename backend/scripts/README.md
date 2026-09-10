# backend/scripts

放**运维 / 一次性工具脚本**（用 `uv run python scripts/xxx.py` 执行）。这些脚本只允许被手动触发，不参与服务启动。

规划中的脚本（随功能批次落地）：

| 脚本 | 用途 | 状态 |
|---|---|---|
| `reset_password.py` | 忘记密码时由管理员重置某账号密码（本项目不做邮箱找回） | 待加（账号体系批次） |
| `cleanup_data.py` | 清理过期上传文件与引擎产物（`data/uploads/`、`data/outputs/`） | 待加（任务生命周期批次） |
| `backup_db.py` | 数据库备份（SQLite `VACUUM INTO`） | 待加（任务生命周期批次） |

约定：

- 脚本必须**幂等**、执行前打印将要做什么、危险操作要求显式传 `--yes`。
- 不引入新依赖（标准库 + 项目已有依赖）。
- 脚本不要 import 应用内会启动 worker / 建后台任务的模块，避免副作用。
