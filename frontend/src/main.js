import { createApp } from 'vue'
import './style.css'
import App from './App.vue'

createApp(App).mount('#app')

// PWA（M3）：仅生产构建注册 Service Worker；开发模式交给 Vite，避免缓存干扰调试。
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      // 注册失败不影响页面功能（如不支持 SW 的环境）
    })
  })
}
