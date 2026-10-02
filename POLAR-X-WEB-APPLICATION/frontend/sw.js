const CACHE = 'polar-x-cloud-v1';
const CORE = ['/', '/style.css?v=20261002-cloud', '/app.js?v=20261002-cloud', '/manifest.json'];
self.addEventListener('install', event => event.waitUntil(caches.open(CACHE).then(c => c.addAll(CORE)).then(()=>self.skipWaiting())));
self.addEventListener('activate', event => event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url=new URL(event.request.url);
  if (url.pathname.startsWith('/api/')) return;
  event.respondWith(fetch(event.request).then(response => { const copy=response.clone(); caches.open(CACHE).then(c=>c.put(event.request,copy)); return response; }).catch(()=>caches.match(event.request).then(r=>r||caches.match('/'))));
});
