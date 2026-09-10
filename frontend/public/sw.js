// docwise 最小 Service Worker（M3 PWA）：
// 1) 安装时预缓存应用壳（index.html / manifest / 图标），支持装主屏后离线打开；
// 2) 页面导航网络优先、离线回退缓存壳；
// 3) 同源静态资源缓存优先（构建产物带 hash，天然不怕陈旧）；
// 4) /api、/files 一律直连不缓存（动态内容，绝不缓存）。
const CACHE_NAME = 'docwise-shell-v1'
const PRECACHE = [
  '/',
  '/index.html',
  '/manifest.webmanifest',
  '/favicon.svg',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/icon-maskable-512.png',
]

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))),
      )
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return

  const url = new URL(request.url)

  // 后端接口与结果文件：永远直连
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/files/')) return

  // 页面导航：网络优先，离线时回退到缓存的应用壳
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone()
          caches.open(CACHE_NAME).then((cache) => cache.put('/', copy))
          return response
        })
        .catch(() => caches.match('/index.html')),
    )
    return
  }

  // 同源静态资源：缓存优先（带运行期回填）
  if (url.origin === self.location.origin) {
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ||
          fetch(request).then((response) => {
            if (response.ok) {
              const copy = response.clone()
              caches.open(CACHE_NAME).then((cache) => cache.put(request, copy))
            }
            return response
          }),
      ),
    )
  }
})
