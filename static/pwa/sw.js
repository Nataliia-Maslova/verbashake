// VerbaShake service worker — Phase E (PWA packaging), 2026-08-24.
//
// This is NOT an offline-first cache for the app itself: every screen is
// server-rendered over a live Streamlit websocket connection (grammar.py's
// Gemini calls, DB reads for mastery/SRS, etc.) — there is no meaningful
// "offline lesson" to serve, and pretending otherwise would just show a
// stale, broken UI with a dead socket. Its only job is to satisfy Chrome's
// installability requirement (a registered SW with a fetch handler) so the
// manifest's "Add to Home Screen" / install prompt actually appears, plus a
// light cache-first pass for the static PWA assets themselves (icons,
// manifest) so the installed icon/splash don't need a live network hit.
//
// Scope note: served from /app/static/pwa/sw.js (Streamlit's static-file
// path, server.enableStaticServing=true in .streamlit/config.toml) — a
// service worker's default scope is the directory it's served from, so
// without the `Service-Worker-Allowed: /` response header (which Streamlit's
// built-in static handler does not let us set) the browser would reject any
// registration that asks for scope "/". Registered with scope
// "/app/static/pwa/" instead (see the registration script in app.py) — that
// is enough for Chrome's installability check, which only requires a
// controlling SW to exist, not that it control the whole origin.

const CACHE_NAME = "verbashake-pwa-v1";
const PRECACHE_URLS = [
  "app/static/pwa/manifest.json",
  "app/static/pwa/icon-192.png",
  "app/static/pwa/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n)))
    )
  );
  self.clients.claim();
});

// Cache-first only for our own static PWA assets (icons/manifest, safe to
// serve stale — icons don't change often and a redeploy bumps CACHE_NAME
// manually if they ever do). Everything else (the Streamlit app itself,
// its websocket upgrade, any Gemini/API traffic) passes straight through to
// the network untouched — caching a live app shell would risk serving a
// broken page after a redeploy changes hashed asset URLs Streamlit itself
// manages.
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || !PRECACHE_URLS.some((p) => url.pathname.endsWith(p))) {
    return; // let the browser handle it normally
  }
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
