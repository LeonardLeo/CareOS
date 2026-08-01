/**
 * Service worker: makes the app shell available with no network.
 *
 * Scope is narrow on purpose. This worker caches the shell — HTML, JS, CSS, manifest — and
 * nothing else. It deliberately does **not** cache API responses, for two reasons:
 *
 * 1. API responses carry PHI, and a cache the app does not manage is a copy of a client's
 *    address that sign-out cannot clear. The schedule cache lives in IndexedDB instead, where
 *    `clearCachedPhi()` can actually delete it.
 * 2. A cached `GET /my-visits` would let the app show yesterday's schedule as if it were
 *    today's, with no indication of age. The IndexedDB cache stores `cachedAt` alongside the
 *    payload so the UI can say how old the data is, which is the honest version of offline.
 *
 * Writes are never intercepted. Queued clock-ins are replayed by the app's own outbox, which
 * knows about ordering and idempotency keys; Background Sync would replay them without either.
 */

const CACHE = "careos-caregiver-shell-v1";

// The token below is replaced at build time with the real emitted asset list — see
// build/precache-plugin.ts. A hand-maintained list here was wrong within one build, because
// the stylesheet is emitted as index.css rather than app.css.
//
// try/catch rather than `?? fallback`: before replacement the token is an undeclared
// identifier, so reading it throws a ReferenceError instead of evaluating to undefined. This
// file is not registered by the dev server at all, so the fallback only covers loading
// /sw.js directly from an unbuilt tree.
const SHELL = (() => {
  try {
    return __PRECACHE_MANIFEST__;
  } catch {
    return ["/", "/index.html", "/manifest.webmanifest"];
  }
})();

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      // Individually, not addAll: addAll rejects atomically, so one asset 404ing during a
      // deploy would leave the caregiver with no cached shell at all.
      .then((cache) => Promise.all(SHELL.map((url) => cache.add(url).catch(() => undefined))))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  // Anything not served from our own origin — above all the API — goes straight to the
  // network. If it fails, the app's offline handling deals with it.
  if (url.origin !== self.location.origin) return;

  // Navigations fall back to the cached shell so a cold start with no signal still opens.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() =>
        caches
          .match("/index.html")
          .then((cached) => cached ?? new Response("Offline", { status: 503 })),
      ),
    );
    return;
  }

  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) {
        // Refresh in the background so the next launch is current, but answer now from cache:
        // a caregiver opening the app on a slow connection should not wait for the network.
        void fetch(request)
          .then((fresh) => {
            if (fresh.ok) return caches.open(CACHE).then((c) => c.put(request, fresh));
          })
          .catch(() => undefined);
        return cached;
      }
      return fetch(request).catch(() => new Response("Offline", { status: 503 }));
    }),
  );
});
