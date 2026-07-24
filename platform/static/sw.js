// Service Worker（接收推送 + 点击打开 app + 注入前端体验增强）
self.addEventListener("install", e => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));

const UI_SCRIPT = '<script src="/static/ui-redesign.js?v=20260724a" defer></script>';

self.addEventListener("fetch", event => {
  const req = event.request;
  const url = new URL(req.url);
  const wantsHtml = req.mode === "navigate" || (req.headers.get("accept") || "").includes("text/html");
  if (req.method !== "GET" || url.origin !== self.location.origin || !wantsHtml) return;

  // 铁律「绝不崩」：注入是锦上添花，任何一步出岔子（离线/异常/非预期响应）
  // 都退回原始请求，页面照常加载——增强失败可以，白屏不行。
  event.respondWith((async () => {
    try {
      const res = await fetch(req);
      const type = res.headers.get("content-type") || "";
      if (!res.ok || !type.includes("text/html")) return res;

      let html = await res.text();
      if (!html.includes("/static/ui-redesign.js")) {
        html = html.replace("</body>", `${UI_SCRIPT}</body>`);
      }
      const headers = new Headers(res.headers);
      headers.set("content-type", "text/html; charset=utf-8");
      headers.set("cache-control", "no-store");
      return new Response(html, { status: res.status, statusText: res.statusText, headers });
    } catch (_) {
      return fetch(req);   // 注入路径挂了就走原路，绝不让页面打不开
    }
  })());
});

self.addEventListener("push", event => {
  let d = { title: "AI 助手", body: "", url: "/" };
  try { if (event.data) d = Object.assign(d, event.data.json()); } catch (_) {}
  event.waitUntil(
    Promise.all([
      self.registration.showNotification(d.title || "AI 助手", {
        body: d.body || "",
        icon: "/static/icon-192.png",
        badge: "/static/icon-192.png",
        data: { url: d.url || "/" },
        vibrate: [80, 40, 80]
      }),
      clients.matchAll({ type: "window", includeUncontrolled: true }).then(list => {
        list.forEach(client => client.postMessage({ type: "GOODLOVE_PUSH", url: d.url || "/" }));
      })
    ])
  );
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  const target = new URL(url, self.location.origin).href;
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then(list => {
      const exact = list.find(c => c.url === target);
      if (exact && "focus" in exact) return exact.focus();
      const current = list[0];
      if (current && "navigate" in current) return current.navigate(target).then(c => c && c.focus());
      if (clients.openWindow) return clients.openWindow(target);
    })
  );
});
