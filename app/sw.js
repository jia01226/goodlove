// 顾得小窝 · 简易离线缓存（壳子离线可开，聊天需联网）
const CACHE = "gude-v1";
const ASSETS = ["./", "./index.html", "./manifest.webmanifest", "./icon.svg"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  // 永不缓存 Claude API 请求
  if (url.hostname.endsWith("anthropic.com")) return;
  // 记忆库 markdown：网络优先（保证最新）
  if (url.pathname.endsWith(".md")) {
    e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
    return;
  }
  // 其余：缓存优先
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
});
