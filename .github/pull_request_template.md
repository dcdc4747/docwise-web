<!-- 提交前请核对：标题符合 Conventional Commits，下面"关联"已填 -->

## 关联
- 关联 Issue：〔`Closes #123` 或 `相关 #123`〕

## 做了什么
〔逐条说明本次改动；涉及契约的，写清改的是 `docs/contracts/` 里哪一份〕

## 怎么验证
〔贴 `ruff` / `pytest` / `vitest` 结果；界面或结果变化贴截图〕

## 自查
- [ ] `cd backend && uv run ruff check . && uv run pytest -q` 通过
- [ ] `cd backend && uv run python scripts/check_contract.py` 通过（改过路由就必须跑）
- [ ] `cd frontend && bun run test && bun run build` 通过
- [ ] 没有提交密钥、`.env`、`backend/data/`、真实姓名与本机绝对路径
- [ ] 改过模块 / 接口 / 数据结构 / 路由 / 引擎层 → 已同步 `docs/ARCHITECTURE.md`
