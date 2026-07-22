(() => {
  if (window.Goodlove) return;

  const cache = new Map();
  const inflight = new Map();

  async function api(path, options = {}) {
    const config = Object.assign({ credentials: "same-origin" }, options);
    const method = String(config.method || "GET").toUpperCase();
    if (method === "GET" && config.cache == null) config.cache = "no-store";
    const response = await fetch(path, config);
    window.dispatchEvent(new CustomEvent(response.ok ? "goodlove:online" : "goodlove:response-error", {
      detail: { path, status: response.status }
    }));
    return response;
  }

  async function getJson(path, { ttl = 0, force = false } = {}) {
    const now = Date.now();
    const saved = cache.get(path);
    if (!force && saved && now - saved.at < ttl) return saved.data;
    if (!force && inflight.has(path)) return inflight.get(path);
    const job = api(path).then(async (response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      cache.set(path, { at: Date.now(), data });
      return data;
    }).finally(() => inflight.delete(path));
    inflight.set(path, job);
    return job;
  }

  function invalidate(prefix = "") {
    for (const key of cache.keys()) if (!prefix || key.startsWith(prefix)) cache.delete(key);
  }

  window.Goodlove = { api, getJson, invalidate };
})();
