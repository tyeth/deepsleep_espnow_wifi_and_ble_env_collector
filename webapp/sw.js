/* Env Hub Analyzer service worker: offline after first load.
 * - app shell: cache-first, refreshed in the background
 * - CDN assets (Plotly, Pyodide + its packages): cache-first forever
 *   (pinned versions in index.html; bump CACHE to invalidate)
 * - device API calls: network only (live data, never cached)
 * Only active on secure origins (the GitHub Pages copy); the device-hosted
 * plain-http copy never registers it.
 */
const CACHE = "envhub-v2";
const SHELL = ["./", "./index.html"];
const CDN_HOSTS = ["cdn.plot.ly", "cdn.jsdelivr.net"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  if (url.pathname.startsWith("/api/")) return; // live device data

  if (CDN_HOSTS.includes(url.hostname)) {
    // cache-first: big pinned assets, works offline after first use
    e.respondWith(
      caches.match(e.request).then(
        (hit) =>
          hit ||
          fetch(e.request).then((resp) => {
            if (resp.ok) {
              const copy = resp.clone();
              caches.open(CACHE).then((c) => c.put(e.request, copy));
            }
            return resp;
          })
      )
    );
    return;
  }

  if (url.origin === location.origin) {
    // stale-while-revalidate for the app shell
    e.respondWith(
      caches.match(e.request).then((hit) => {
        const net = fetch(e.request)
          .then((resp) => {
            if (resp.ok) {
              const copy = resp.clone();
              caches.open(CACHE).then((c) => c.put(e.request, copy));
            }
            return resp;
          })
          .catch(() => hit);
        return hit || net;
      })
    );
  }
});
