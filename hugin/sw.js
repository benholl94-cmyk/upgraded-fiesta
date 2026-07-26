/* HUGIN Service Worker — Cache-First, Offline-capable */
const CACHE = 'hugin-v7';
const SHELL = [
  './',
  './index.html',
  './hugin.html',
  './manifest.json',
  './icon-512.svg',
  './icon-192.svg',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  /* AI provider calls → immer Network, kein Cache */
  const AI_HOSTS = [
    'api.groq.com', 'generativelanguage.googleapis.com',
    'text.pollinations.ai', 'api-inference.huggingface.co',
    'openrouter.ai', 'api.featherless.ai', 'router.huggingface.co',
    'api.novita.ai', 'models.inference.ai.azure.com',
    'api.together.xyz', 'api.cohere.com', 'api.x.ai',
    'api.mistral.ai', 'api.cerebras.ai',
  ];
  if (AI_HOSTS.includes(url.hostname)) {
    return; /* pass-through, kein Cache */
  }

  /* Shell-Ressourcen → Cache-First, Netzwerk-Fallback */
  e.respondWith(
    caches.match(e.request).then(cached => {
      if (cached) return cached;
      return fetch(e.request).then(resp => {
        if (resp.ok && e.request.method === 'GET') {
          const clone = resp.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return resp;
      }).catch(() => caches.match('./index.html'));
    })
  );
});
