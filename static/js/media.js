/**
 * window.secureMedia — загрузка защищённых /media/ файлов с JWT.
 *
 * Сервер отдаёт /media/ только аутентифицированным запросам своей компании
 * (см. apps/core/media_views.py). Но <img src> и <a href> заголовок
 * Authorization не ставят — браузер грузил бы их анонимно и получал 401.
 * Поэтому модуль находит same-origin ссылки на /media/, догружает байты
 * через fetch с Bearer-токеном (+ один ретрай через refresh при 401) и
 * подменяет src/href на blob-URL. Абсолютные URL другого хоста (S3-бакет)
 * не трогаем — их сервер хранит и отдаёт сам.
 *
 * Ошибка загрузки НЕ разлогинивает пользователя и НЕ показывает тост:
 * исходный src остаётся на месте и срабатывает штатный onerror-фолбэк
 * компонента (эмодзи-заглушка). CSP уже разрешает blob: в img-src.
 */
(function () {
    'use strict';

    const MEDIA_PREFIX = '/media/';

    // path -> blob-URL. Один и тот же логотип/аватар в десяти местах
    // грузится из сети один раз.
    const blobCache = new Map();
    // path -> Promise: параллельные вставки одного URL ждут один запрос.
    const inflight = new Map();

    /**
     * Извлекает same-origin путь /media/... из атрибута. null — не наш случай
     * (blob:/data:, чужой хост, не /media/, мусор).
     */
    function mediaPath(raw) {
        if (!raw || typeof raw !== 'string') return null;
        const src = raw.trim();
        if (!src || src.startsWith('blob:') || src.startsWith('data:')) {
            return null;
        }
        let url;
        try {
            url = new URL(src, window.location.origin);
        } catch (e) {
            return null;
        }
        if (url.origin !== window.location.origin) return null;
        if (!url.pathname.startsWith(MEDIA_PREFIX)) return null;
        return url.pathname;
    }

    /**
     * Байты файла как blob-URL. 401 с живым refresh — один ретрай через
     * window.api.refreshToken (как в api.request, но БЕЗ expireSession:
     * битая картинка не должна выкидывать пользователя на страницу входа).
     */
    async function fetchBlob(path) {
        if (blobCache.has(path)) return blobCache.get(path);
        if (inflight.has(path)) return inflight.get(path);
        const job = (async () => {
            const tokens = window.api ? window.api.getTokens() : {};
            const withAuth = (access) => (access
                ? { Authorization: `Bearer ${access}` }
                : {});
            let response = await fetch(path, {
                headers: withAuth(tokens.access),
            });
            if (response.status === 401 && tokens.refresh && window.api) {
                const fresh = await window.api
                    .refreshToken(tokens.refresh)
                    .catch(() => null);
                if (fresh) {
                    response = await fetch(path, {
                        headers: withAuth(fresh),
                    });
                }
            }
            if (!response.ok) {
                throw new Error(`media request failed: ${response.status}`);
            }
            const objectUrl = URL.createObjectURL(await response.blob());
            blobCache.set(path, objectUrl);
            return objectUrl;
        })();
        inflight.set(path, job);
        try {
            return await job;
        } finally {
            inflight.delete(path);
        }
    }

    function secureElement(el, attr) {
        if (!el || el.dataset.mediaSecured) return;
        const path = mediaPath(el.getAttribute(attr));
        if (!path) return;
        el.dataset.mediaSecured = '1';
        fetchBlob(path).then(
            (objectUrl) => {
                el.setAttribute(attr, objectUrl);
            },
            () => {
                // Не загрузилось (403 чужой файл, сеть, протухшая сессия):
                // возвращаем как было — сработает onerror-фолбэк компонента.
                delete el.dataset.mediaSecured;
            },
        );
    }

    function scan(root) {
        if (!root || typeof root.querySelectorAll !== 'function') return;
        root.querySelectorAll('img[src]').forEach((el) => {
            secureElement(el, 'src');
        });
        root.querySelectorAll('a[href]').forEach((el) => {
            secureElement(el, 'href');
        });
    }

    let observer = null;

    function init() {
        if (observer) return;
        scan(document);
        // Динамический контент (сообщения чата по WebSocket, подгрузки
        // списков) тоже проходит через защиту без правок в компонентах.
        observer = new MutationObserver((mutations) => {
            for (const mutation of mutations) {
                mutation.addedNodes.forEach((node) => {
                    if (!node || node.nodeType !== 1) return;
                    if (node.tagName === 'IMG' && node.hasAttribute('src')) {
                        secureElement(node, 'src');
                    } else if (node.tagName === 'A' && node.hasAttribute('href')) {
                        secureElement(node, 'href');
                    }
                    scan(node);
                });
            }
        });
        observer.observe(document.body, { childList: true, subtree: true });
    }

    function reset() {
        blobCache.forEach((objectUrl) => {
            try {
                URL.revokeObjectURL(objectUrl);
            } catch (e) {
                /* уже отозван */
            }
        });
        blobCache.clear();
        inflight.clear();
        document.querySelectorAll('[data-media-secured]').forEach((el) => {
            delete el.dataset.mediaSecured;
        });
    }

    window.secureMedia = {
        init,
        reset,
        scan,
        // Экспортированы для unit-тестов (tests/frontend/media.test.js).
        _mediaPath: mediaPath,
        _fetchBlob: fetchBlob,
    };
})();
