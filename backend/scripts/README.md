# backend/scripts

放**运维 / 一次性工具脚本**（用 `uv run python scripts/xxx.py` 执行）。这些脚本只允许被手动触发，不参与服务启动。

规划中的脚本（随功能批次落地）：

| 脚本 | 用途 | 状态 |
|---|---|---|
| `reset_password.py` | 忘记密码时由管理员重置某账号密码（本项目不做邮箱找回） | 已加（B 批） |
| `cleanup_data.py` | 清理孤儿产物（`data/outputs/`、无人引用的 `data/uploads/`、陈旧引擎临时目录）；**默认干跑**，加 `--yes` 才真删 | 已加（E 批） |
| `backup_db.py` | 数据库备份（SQLite `VACUUM INTO`，备份后自动校验并只留最近 N 份） | 已加（E 批） |
| `migrate_v2_schema.py` | 形态 v2 数据层一次性迁移：建 11 张新表 + `tasks.reading_status` + 种三条内置智能集合；**默认只预览**，`--apply` 才写，`--restore` 能撤 | 已加（B1） |
| `seed_smart_collections.py` | 给全部账号补齐**内置智能集合**三条（待读/在读/已读）；**默认只预览**，`--apply` 才写。⚠️ 幂等且**故意不用 `_migration_marker`**（收敛型：新账号随时出现，本来就该能反复跑）；正常情况下不用手工跑——`GET /api/smart-collections` 会自愈 | 已加（M1/D3） |

服务启动时也会自动回收「孤儿结果目录 + 陈旧引擎临时目录」，所以 `cleanup_data.py` 是"想立刻清一次"时用的手动工具。

约定：

- 脚本必须**幂等**、执行前打印将要做什么、危险操作要求显式传 `--yes`。
- 不引入新依赖（标准库 + 项目已有依赖）。
- 脚本不要 import 应用内会启动 worker / 建后台任务的模块，避免副作用。
