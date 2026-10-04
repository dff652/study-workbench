// Only this public, generic page is stored. No private response is cached.
const CACHE_PREFIX = "study-workbench-offline-";
const CACHE_NAME = "{{ cache_name|escapejs }}";
const OFFLINE_URL = "{{ offline_url|escapejs }}";

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const response = await fetch(OFFLINE_URL, {credentials: "omit", cache: "no-store"});
    if (!response.ok || response.redirected ||
        /private|no-store/i.test(response.headers.get("Cache-Control") || "")) {
      throw new Error("Offline page is not a cacheable public asset");
    }
    const cache = await caches.open(CACHE_NAME);
    await cache.put(OFFLINE_URL, response);
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET" || request.mode !== "navigate" ||
      new URL(request.url).origin !== self.location.origin) return;
  event.respondWith((async () => {
    try {
      return await fetch(request);
    } catch (error) {
      const cache = await caches.open(CACHE_NAME);
      const offline = await cache.match(OFFLINE_URL);
      return offline || Response.error();
    }
  })());
});
