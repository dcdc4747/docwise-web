import { readdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

/**
 * 把 pdf.js 的「标准字体数据」发出去（dev 直接发，build 落到 dist/pdfjs/standard_fonts/）。
 *
 * 为什么不塞进 public/ 直接提交：那是 762 KB 的第三方二进制字体（14 个 .pfb/.ttf），
 * 仓库约定「大文件不走 git」。从 node_modules 发出去，版本跟着 package.json 走，
 * 谁 clone 下来 install 一次就有。
 *
 * 不配会怎样：pdf.js 画"没嵌字体的标准字体"时会告警并退化成替代字体
 * （实测 EBSCO_05-mono 那份就触发了）——页面上字会变形或缺失。
 */
function pdfjsStandardFonts() {
  const dir = fileURLToPath(new URL('./node_modules/pdfjs-dist/standard_fonts/', import.meta.url))
  const list = () => {
    try {
      return readdirSync(dir)
    } catch {
      return []
    }
  }
  const typeOf = (name) =>
    name.endsWith('.pfb') ? 'application/octet-stream' : name.endsWith('.ttf') ? 'font/ttf' : 'text/plain'

  return {
    name: 'docwise:pdfjs-standard-fonts',
    configureServer(server) {
      server.middlewares.use('/pdfjs/standard_fonts', (req, res, next) => {
        const name = path.basename(decodeURIComponent((req.url || '').split('?')[0]))
        if (!list().includes(name)) return next()
        res.setHeader('Content-Type', typeOf(name))
        res.end(readFileSync(path.join(dir, name)))
      })
    },
    generateBundle() {
      for (const name of list()) {
        this.emitFile({
          type: 'asset',
          fileName: `pdfjs/standard_fonts/${name}`,
          source: readFileSync(path.join(dir, name)),
        })
      }
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue(), pdfjsStandardFonts()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  // 前端测试（vitest）：跑 `bun run test` / `npm test`。
  // 目的是兜住"能编译、但页面渲染出问题"这类只在浏览器里才看得见的错——
  // F 批就发生过"模板插值函数没写括号，函数源码被印在页面上"，而 build 一点错都不报。
  test: {
    environment: 'happy-dom',
    include: ['tests/**/*.test.js'],
    setupFiles: ['tests/setup.js'],
  },
})
