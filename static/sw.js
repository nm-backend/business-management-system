/**
 * SkladPro.Nod — Service Worker
 * Push-уведомления и кэширование офлайн-ресурсов.
 * Регистрируется в app.js, активируется при разрешении пользователя.
 */
const CACHE_NAME = 'skladpro-v1';

// ── Install: кэшируем базовые ресурсы ──
self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(['/']).catch(() => {});
    })
  );
});

// ── Activate: удаляем старые кэши ──
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      );
    }).then(() => self.clients.claim())
  );
});

// ── Message from main thread: показать уведомление ──
self.addEventListener('message', (event) => {
  if (!event.data) return;
  const data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;

  if (data.type === 'show_notification') {
    self.registration.showNotification(data.title || 'SkladPro.Nod', {
      body: data.body || '',
      tag: data.tag || 'notification',
      vibrate: [200, 100, 200],
      requireInteraction: true,
      data: data.data || {},
    });
  }
});

// ── Fetch: офлайн-кэш для статики (stale-while-revalidate) ──
// Раньше кэш наполнялся в install, но fetch-обработчика не было — кэш
// никогда не читался, офлайн не работал. API-запросы и навигация не
// кэшируются (SPA требует живого сервера).
self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname === '/') return;

  event.respondWith(
    caches.open(CACHE_NAME).then(async (cache) => {
      const cached = await cache.match(request);
      const network = fetch(request).then((response) => {
        if (response && response.ok) cache.put(request, response.clone());
        return response;
      }).catch(() => cached);
      return cached || network;
    })
  );
});

// ── Notification click: фокусируем или открываем приложение ──
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const urlToOpen = event.notification.data?.url || '/';

  if (event.action === 'close') return;

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      // Если уже есть окно — фокусируем и навигируем
      if (clientList.length > 0) {
        const client = clientList[0];
        client.focus();
        // navigate доступен только для клиентов того же origin
        if (client.navigate) {
          client.navigate(urlToOpen).catch(() => {});
        }
        return;
      }
      // Иначе открываем новое окно
      if (clients.openWindow) {
        return clients.openWindow(urlToOpen);
      }
    })
  );
});

// ── Push event (для серверного VAPID push — задел на будущее) ──
self.addEventListener('push', (event) => {
  let data = { title: 'SkladPro.Nod', body: '' };
  if (event.data) {
    try {
      data = event.data.json();
    } catch (e) {
      data.body = event.data.text();
    }
  }
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      vibrate: [200, 100, 200],
      requireInteraction: true,
      data: data.data || {},
    })
  );
});
