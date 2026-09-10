import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
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
