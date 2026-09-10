# frontend（docwise-web 前端）

Vue 3 + Vite + Naive UI。技术约定：优先使用 bun。

## 启动

```bash
bun install
bun dev
```

开发服务器默认运行在 http://127.0.0.1:5173 ，`/api` 会代理到
http://127.0.0.1:8000（后端）。请先启动 backend 再访问首页。

## 构建

```bash
bun run build   # 产物在 dist/（manifest / sw.js / 图标随 public/ 一并拷贝）
bun run preview # 本地预览构建产物（默认 4173 端口）
```

## PWA 与手机真机访问（M3）

- **装主屏/离线**：构建产物自带 `manifest.webmanifest` + 最小 `sw.js`
  （应用壳离线缓存；`/api`、`/files` 永远直连不缓存）。用 HTTPS 或 localhost
  打开即可安装；手机装主屏后以 standalone 全屏运行。
- **绝对 API base**：所有 `/api` 调用走 `src/api.js` 的 `apiUrl()`。后端地址按
  优先级解析：URL 参数 `?apiBase=` > localStorage（`docwise_api_base`）>
  构建时 `VITE_API_BASE` > 空（同源相对路径）。
- **手机连电脑后端**（前端与后端不同源时）：
  ```bash
  # 方式一：构建时指定（电脑局域网 IP）
  VITE_API_BASE=http://192.168.1.5:8000 bun run build
  # 方式二：不改构建，浏览器打开页面时带参数
  #   http://192.168.1.5:4173/?apiBase=http://192.168.1.5:8000
  ```
  并在后端 `.env` 追加跨域白名单（手机页面的来源）：
  ```
  DOCWISE_CORS_ORIGINS=http://192.168.1.5:4173
  ```
  （默认已允许 localhost / 127.0.0.1 的 5173 与 4173。）
- 同源部署（前端静态文件由后端同端口托管）时无需任何配置。
