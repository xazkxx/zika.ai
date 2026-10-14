/* ERP PWA 服务工作者
 *
 * 作用：
 * 1. 首次安装时缓存应用外壳（页面、图标、清单）
 * 2. 静态资源：优先用缓存（离线也能打开），后台悄悄更新
 * 3. 业务接口 /api：永远走网络，不缓存（保证数据实时）
 *
 * 注意：改了版本号 CACHE_VERSION 后，旧缓存会自动清理。
 */
const CACHE_VERSION = 'erp-pwa-v1';
const CACHE_NAME = `${CACHE_VERSION}-shell`;

// 应用外壳：离线打开至少要有的文件
const APP_SHELL = [
  '/',
  '/manifest.webmanifest',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
];

// 安装：预缓存应用外壳
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
  );
});

// 激活：删除旧版本缓存
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== CACHE_NAME)
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

// 请求拦截策略
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // 业务接口：只走网络，失败时返回提示（不缓存真实数据）
  if (url.pathname.startsWith('/api/')) {
    return;
  }

  // 页面导航：网络优先，断网时退回缓存首页
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put('/', copy));
          return response;
        })
        .catch(() => caches.match('/'))
    );
    return;
  }

  // 其他静态资源：缓存优先 + 后台更新（stale-while-revalidate）
  if (event.request.method === 'GET') {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        const network = fetch(event.request)
          .then((response) => {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) =>
              cache.put(event.request, copy)
            );
            return response;
          })
          .catch(() => cached);
        return cached || network;
      })
    );
  }
});
