/* HUGIN Service Worker — Cache-First, Offline-capable */
/* Cache-Version bei jeder Shell-Aenderung erhoehen: 'activate' loescht alles,
   was nicht CACHE heisst. Bleibt die Version stehen, behaelt ein bereits
   installiertes Geraet die alte Shell — die neuen Icons kaemen dort nie an. */
const CACHE = 'hugin-v8';
const SHELL = [
  './',
  './index.html',
  './hugin.html',
  './manifest.json',
  /* PNG zuerst: iOS wertet fuer den Home-Bildschirm kein SVG aus, und was
     nicht im Shell-Cache liegt, fehlt bei der Offline-Installation. */
  './apple-touch-icon-180.png',
  './icon-192.png',
  './icon-512.png',
  './icon-512.svg',
  './icon-192.svg',
];

/* Ohne diese beiden gibt es keine App — schlagen sie fehl, soll die
   Installation fehlschlagen. */
const CORE = ['./', './index.html'];

/* `cache.addAll` ist alles-oder-nichts: EINE fehlende Datei laesst die ganze
   Installation scheitern, und damit faellt der Offline-Betrieb komplett aus —
   nicht nur das fehlende Symbol. Vorher stand die gesamte Shell in einem
   einzigen addAll; mit den drei neu hinzugekommenen PNG-Dateien waeren das
   drei zusaetzliche Gelegenheiten gewesen, alles zu verlieren.
   Der Kern bleibt deshalb hart, der Rest wird einzeln und nachsichtig
   geholt — ein fehlendes Icon kostet dann das Icon und nicht die App. */
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(async c => {
      await c.addAll(CORE);
      const optional = SHELL.filter(url => !CORE.includes(url));
      const results = await Promise.allSettled(optional.map(url => c.add(url)));
      results.forEach((r, i) => {
        if (r.status === 'rejected') {
          console.warn('SW: Shell-Eintrag nicht cachebar:', optional[i], r.reason);
        }
      });
      await self.skipWaiting();
    })
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
