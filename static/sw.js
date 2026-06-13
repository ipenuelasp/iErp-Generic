const CACHE_NAME = 'ierp-v2';

const STATIC_ASSETS = [
  '/static/img/iErp_4k_sinfondo.png',
  '/static/img/favicon.png',
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache =>
      Promise.allSettled(STATIC_ASSETS.map(url => cache.add(url).catch(() => {})))
    )
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;

  const url = new URL(event.request.url);
  const esAssetEstatico = url.pathname.startsWith('/static/') &&
    /\.(png|jpg|jpeg|gif|webp|svg|ico|woff|woff2|ttf|css)$/.test(url.pathname);

  if (esAssetEstatico) {
    event.respondWith(
      caches.match(event.request).then(cached => {
        if (cached) return cached;
        return fetch(event.request).then(response => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
          }
          return response;
        });
      })
    );
    return;
  }

  event.respondWith(
    fetch(event.request, { credentials: 'same-origin' }).catch(() => {
      if (event.request.mode === 'navigate') {
        return new Response(
          `<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">
          <meta name="viewport" content="width=device-width,initial-scale=1">
          <title>Sin conexion</title></head>
          <body style="font-family:sans-serif;background:#f1f5f9;display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center;padding:24px;">
            <div>
              <h1 style="font-size:1.25rem;font-weight:700;color:#334155;margin-bottom:8px;">Sin conexion</h1>
              <p style="color:#64748b;font-size:0.875rem;margin-bottom:24px;">Necesitas conexion a internet para usar iErp.</p>
              <button onclick="location.reload()" style="background:#1e2d4f;color:#fff;padding:12px 28px;border-radius:12px;font-weight:600;font-size:0.875rem;border:none;cursor:pointer;">
                Reintentar
              </button>
            </div>
          </body></html>`,
          { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
        );
      }
      return new Response('', { status: 503 });
    })
  );
});
