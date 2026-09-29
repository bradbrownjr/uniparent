// UniParent service worker: makes the app installable and quick to open.
// Never caches /api — WiFi state must always be live.
const CACHE = 'uniparent-shell-v1'
const SHELL = ['/', '/manifest.webmanifest', '/icon-192.png']

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()))
})

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()))
})

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url)
  if (e.request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return
  // Network first so updates show up right away; fall back to the cached shell when offline.
  e.respondWith(
    fetch(e.request)
      .then((r) => {
        if (r.ok && (e.request.mode === 'navigate' || url.pathname.startsWith('/assets/'))) {
          const copy = r.clone()
          caches.open(CACHE).then((c) => c.put(e.request.mode === 'navigate' ? '/' : e.request, copy))
        }
        return r
      })
      .catch(() => caches.match(e.request.mode === 'navigate' ? '/' : e.request).then((m) => m || Response.error())),
  )
})
