// Service Worker（接收推送 + 点击打开 app）
self.addEventListener("install", e => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));

self.addEventListener("push", event => {
  let d = { title: "AI 助手", body: "", url: "/" };
  try { if (event.data) d = Object.assign(d, event.data.json()); } catch (_) {}
  event.waitUntil(
    self.registration.showNotification(d.title || "AI 助手", {
      body: d.body || "",
      icon: "/static/icon-192.png",
      badge: "/static/icon-192.png",
      data: { url: d.url || "/" },
      vibrate: [80, 40, 80]
    })
  );
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then(list => {
      for (const c of list) { if ("focus" in c) return c.focus(); }
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});
