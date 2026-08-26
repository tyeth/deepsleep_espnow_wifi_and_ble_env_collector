/* Env Hub Analyzer service worker: offline after first load.
 * - app shell + demo dataset: precached, stale-while-revalidate
 * - CDN assets (Plotly, Pyodide + its packages): cache-first FOREVER
 *   (pinned versions in index.html; bump CACHE to invalidate). Script
 *   tags fetch no-cors, so the responses are OPAQUE (status 0) — they
 *   must be cached anyway or nothing "big" survives offline. Downloaded
 *   once, reused forever (same model as Chrome's on-device AI).
 * - device API calls: network only (live data, never cached)
 * Only active on secure origins (the GitHub Pages copy); the device-hosted
 * plain-http copy never registers it.
 */
const CACHE = "envhub-v11";
const SHELL = [
  "./",
  "./index.html",
  "./manifest.json",
  "./icon.svg",
  "./sample/days.json",
  "./sample/2026-08-22.csv",
  "./sample/2026-08-23.csv",
  "./sample/2026-08-24.csv",
];
// entry scripts wanted on every load: precache best-effort so going
// offline right after the first visit still leaves charts working
const CDN_PRECACHE = [
  "https://cdn.plot.ly/plotly-2.35.2.min.js",
  "https://cdn.jsdelivr.net/pyodide/v0.26.2/full/pyodide.js",
];
const CDN_HOSTS = ["cdn.plot.ly", "cdn.jsdelivr.net"];

function cacheable(resp) {
  // opaque = no-cors cross-origin (script tags): status reads 0 but the
  // body is real; 206 partials are not cacheable
  return resp && (resp.ok || resp.type === "opaque") && resp.status !== 206;
}

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then(async (c) => {
      await c.addAll(SHELL);
      // best-effort: never fail install over CDN reachability
      await Promise.allSettled(
        CDN_PRECACHE.map(async (u) => {
          const req = new Request(u, { mode: "no-cors" });
          const resp = await fetch(req);
          if (cacheable(resp)) await c.put(req, resp);
        })
      );
    })
  );
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
  if (url.pathname.startsWith("/api/") || url.pathname.includes("/api/"))
    return; // live device data

  if (CDN_HOSTS.includes(url.hostname)) {
    // cache-first: big pinned assets, work offline after first use
    e.respondWith(
      caches.match(e.request, { ignoreVary: true }).then(
        (hit) =>
          hit ||
          fetch(e.request).then((resp) => {
            if (cacheable(resp)) {
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
    // navigations: any query string (?demo=1 etc.) must hit the cached
    // shell offline — match ignoring the search part
    const isNav = e.request.mode === "navigate";
    e.respondWith(
      caches
        .match(e.request, { ignoreSearch: isNav })
        .then((hit) => {
          const net = fetch(e.request)
            .then((resp) => {
              if (cacheable(resp) && resp.type !== "opaque") {
                const copy = resp.clone();
                caches.open(CACHE).then((c) => c.put(e.request, copy));
              }
              return resp;
            })
            .catch(() =>
              hit || (isNav ? caches.match("./index.html") : undefined)
            );
          return hit || net;
        })
    );
  }
});
