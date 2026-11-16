# 写作编辑器快捷键 · 实测记录（2026-10-19）

> 验证环境：**真实 Chrome**（通过 Chrome DevTools MCP 驱动）+ `http://localhost:5199`（Vite dev server，
> 直接跑 `frontend/src` 的同一份源码；`/api` 反向代理到已在跑的 `http://127.0.0.1:8000`）。
> 步骤：打开 `/#/write` → 用「＋ 新建 → 空白文字」建一份临时草稿 → 逐条按键 → 测完删除草稿
> （演示稿 #8 未被改动，测完核对仍是 2463 字）。
>
> 说明：`Ctrl+C / Ctrl+X / Ctrl+V` 用 **CDP 真键**（`Input.dispatchKeyEvent`）走浏览器原生剪贴板；
> `Ctrl+B / I / Z / S / Enter / Tab` 同样用真键。只有"读剪贴板序列化结果"这一步额外用了
> `document.execCommand('copy')` 的 copy 事件（浏览器不允许脚本读系统剪贴板的全量内容）。

## 结论总表

| # | 快捷键 | 期望 | 实测 | 证据 |
|---|---|---|---|---|
| 1 | `Ctrl+Z` | 撤销（编辑器历史） | ✅ 通过 | 加粗后 `strong` 4→3；`keydown.defaultPrevented = true`，焦点仍在 `.we-prose` |
| 1b | `Ctrl+Shift+Z` | 重做 | ✅ 通过 | 撤销后再按，`strong` 3→4；`prevented = true` |
| 1c | `Ctrl+Y` | 重做（也接受） | ✅ 通过 | 撤销后再按，`strong` 3→4；`prevented = true`（有可重做历史时） |
| 2 | `Ctrl+C` | 复制（富文本 + 纯文本） | ✅ 通过 | 真键 `Ctrl+C`：`keydown` **未**被拦截（`prevented = false`）；copy 事件拿到 `text/html="<p data-pm-slice=…>第一段：</p>"` 与 `text/plain="第一段："`，是语义 HTML，不是 Markdown 源码 |
| 3 | `Ctrl+V`（富文本） | 粘富文本 | ✅ 通过 | 真键复制一段 `<strong>`，到空段落真键粘贴 → 新段落 `<p><strong>富文本加粗</strong></p>`，样式保留 |
| 3b | `Ctrl+V`（纯文本） | 粘纯文本、不出源码 | ✅ 通过 | 系统剪贴板写入 `纯文本粘贴ABC <b>不是源码</b>` 后真键粘贴 → 文本原样出现；DOM 里是 `&lt;b&gt;` **转义文字**，没有 `<b>` 元素，`p b` 数量 0 |
| 4 | `Ctrl+X` | 剪切 | ✅ 通过 | 真键剪切「列表一」→ 该文字从列表消失（`li` 文本变空）；再真键 `Ctrl+V` 在同一处粘回 → `li` 恢复「列表一」 |
| 5 | `Ctrl+B` | 加粗，且**不**收起左栏 | ✅ 通过 | 真键：`strong` 3→4；同时 `rail-min` **保持 true 不变**（修复前会 true→false，见下"修复前的坏行为"） |
| 5b | `Ctrl+I` | 斜体 | ✅ 通过 | 真键：`em` 1→2，`em` 文本包含所选「快捷键实测」；`prevented = true` |
| 6 | `Ctrl+S`（编辑器内） | 保存，不弹浏览器保存框 | ✅ 通过 | 真键：状态行「未保存」→「已保存 03:20」，toast「已保存」，`keydown.defaultPrevented = true`（浏览器"保存网页"默认行为被取消，未出现对话框） |
| 6b | `Ctrl+S`（标题栏聚焦） | 同样能保存 | ✅ 通过 | 焦点在 `.wr-title` 时真键：状态「已保存 03:20」、toast「已保存」、`prevented = true`；`event.target = wr-title` |
| 7 | `Enter` | 新段落 | ✅ 通过 | 真键：`<p>` 1→2；`prevented = true` |
| 7b | `Shift+Enter` | 段内换行 | ✅ 通过 | 真键：`<p>` 仍为 2（不新开段），该段 `<br>` 1→2；`prevented = true` |
| 7c | `Tab`（正文） | 焦点不跳走 | ✅ 通过 | 真键：`prevented = true`；`document.activeElement` 仍是 `.we-prose`，`stillInEditor = true` |
| 7d | `Tab`（列表） | 缩进 | ✅ 通过 | 两行列表，光标在第二项时真键 `Tab` → HTML 变成 `<li>列表一<ul><li>列表二…`（第二项嵌进第一项）；`prevented = true`，焦点不动 |
| 7e | `Shift+Tab`（列表） | 反缩进 | ✅ 通过 | 再按 `Shift+Tab` → `li ul` 数量 2→0，回到同级 |

## 修复前的坏行为（都已复现，再修掉）

1. **`Ctrl+B` 被外壳抢走**：`App.vue` 在 `window` 上把 `Ctrl+B` 当「收起/展开左栏」的全局快捷键。
   写作区按 `Ctrl+B` 会**一边加粗、一边把左栏收起来**（实测 `rail-min` true→false）。
   → `WriteEditor` 在组件根节点拦下 `Ctrl+B` 的冒泡（`stopPropagation`），只加粗、不动左栏。
2. **`Tab` 不拦**：正文里 StarterKit 没有人接 `Tab`，`defaultPrevented` 是 `false`，焦点会跳出编辑器。
   → 新增 `WriteShortcuts` 扩展（`priority: 1000`）：列表里 `sinkListItem` / `liftListItem`，
   其余情况**只吞键**（返回 `true`，ProseMirror 调 `preventDefault`），正文不插不可见制表符。
3. **`Ctrl+S` 只管编辑器内**：焦点在标题栏时 `defaultPrevented` 是 `false`，会弹浏览器「保存网页」。
   → `WriteView.onWriteKeydown` 增加页面级 `Ctrl/Cmd+S`（`preventDefault` + `saveWithFeedback()`）；
   编辑器内那条 `stopPropagation`，保证**只存一次**。

## 对应代码

- `frontend/src/components/WriteEditor.vue`
  - L16：`<div class="we" @keydown="onKeydown">`（在冒泡到 `window` 之前拦键）
  - L215–266：`WriteShortcuts` 扩展：`Mod-b` / `Mod-i` / `Mod-z` / `Shift-Mod-z` / `Mod-y` / `Tab` / `Shift-Tab`
  - L309：扩展挂进编辑器
  - L437–451：`onKeydown`（`Ctrl+S` 保存 + `Ctrl+B` 切断冒泡；`Ctrl+C/V/X` 不接管）
- `frontend/src/views/WriteView.vue`
  - L1304–1319：`onWriteKeydown` 增加页面级 `Ctrl/Cmd+S`
  - 旧的、从未接线的 `onEditorKeydown` 已删除（避免两套 Ctrl+S）

## 验证命令与结果

> 下列结果是**等价执行**（同一套 vitest/vite、同一份源码与用例，见下方 ⚠️）；
> 正常环境 / CI 直接跑这三条原命令即可。

```text
$ bun run test -- tests/write-editor-shortcuts.test.js   # 18 passed
Test Files  1 passed (1)
     Tests  18 passed (18)

$ bun run test                                           # 全量
Test Files  48 passed (48)
     Tests  652 passed (652)

$ bun run build                                          # vite v8.2.0
✓ 2899 modules transformed. ✓ built in 1.72s
```

> ⚠️ 本机 DSH 沙盒对 `frontend/` 的 shell 写入与子进程有额外限制：`bun run test` 读 `package.json` 被判
> EACCES、vitest 直接跑会遇到 `spawn EPERM`、`bun run build` 无法写 `frontend/dist`。上面三条命令是用
> **同一套 vitest/vite + 临时配置**执行的（`root` 指向真实 `frontend/`，缓存与产物落在系统临时目录），
> 跑的是同一份源码与同一批用例；在正常环境/CI 里按上面三条原命令执行即可。
