/* HUGIN Service Worker — Netzwerk zuerst für die eigene Hülle, Cache als Rückfall.
 *
 * ## Warum nicht mehr Cache-First
 *
 * Die vorige Fassung lieferte die Hülle aus dem Cache und ging nur bei einem
 * Fehlschlag ins Netz. Der Cache-Schlüssel war eine Zahl von Hand (`hugin-v7`),
 * und sie wurde beim letzten Umbau von `hugin.html` **nicht** hochgezählt.
 * Folge, gemessen und nicht vermutet: auf jedem bereits installierten iPhone
 * blieb die alte Seite stehen. Der neu eingebaute Kern-Anbieter war
 * ausgeliefert und trotzdem unerreichbar.
 *
 * Eine Regel, die nur greift, wenn jemand an sie denkt, greift irgendwann
 * nicht. Deshalb ist die Strategie umgedreht: online zählt immer das Netz,
 * offline der Cache. Der Schlüssel darunter bleibt — er räumt alte Bestände
 * ab —, aber die Aktualität hängt nicht mehr an ihm.
 *
 * ## Warum keine Liste fremder Hosts mehr
 *
 * Vorher stand hier eine Aufzählung von 14 AI-Hosts, die nicht gecacht werden
 * sollten. Jeder neue Anbieter musste nachgetragen werden, und **das eigene
 * Gateway stand nie darin**: ein Chat-Aufruf an den eigenen Port lief damit in
 * den Hüllen-Zweig, und wenn das Gateway nicht erreichbar war, antwortete der
 * Worker mit `index.html` — die PWA bekam HTML, wo sie einen Ereignisstrom
 * erwartete, und der Fehler sah nach allem aus, nur nicht nach "Gateway aus".
 *
 * Die Regel ist jetzt strukturell statt namentlich: **nur eigene GET-Anfragen**
 * werden überhaupt angefasst. Alles Fremde und alles, was kein GET ist — also
 * jeder Anbieter und jeder `POST /chat` — geht unberührt durch. Diese Regel
 * kann nicht veralten.
 */
const CACHE = 'hugin-v8';
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

  /* Fremde Herkunft oder kein GET → unberührt durchlassen.
     Deckt jeden AI-Anbieter ab, das eigene Gateway, und alles Künftige. */
  if (url.origin !== self.location.origin || e.request.method !== 'GET') {
    return;
  }

  /* Eigene Hülle: Netz zuerst, Cache als Rückfall.
     Ein erfolgreicher Abruf frischt den Cache auf, damit der Offline-Stand
     nicht beliebig alt wird. */
  e.respondWith(
    fetch(e.request)
      .then(resp => {
        if (resp.ok) {
          const clone = resp.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return resp;
      })
      .catch(() =>
        caches.match(e.request).then(cached => cached || caches.match('./index.html'))
      )
  );
});
