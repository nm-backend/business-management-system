/**
 * APIClient - клиент для взаимодействия с Django REST API.
 *
 * Управляет JWT токенами, fingerprint'ом устройства и автоматическим
 * обновлением при истечении срока.
 *
 * Fingerprint — UUID устройства, хранящийся в localStorage. Сервер встраивает
 * его хеш в refresh token. При token refresh сервер проверяет fingerprint —
 * если не совпадает, значит токен украден, и все сессии пользователя
 * инвалидируются.
 */
class APIClient {
    constructor() {
        this.baseUrl = '/api/v1';
    }

    // ── Fingerprint ────────────────────────────────────────────────

    /**
     * Возвращает device fingerprint — UUID v4 без дефисов.
     * Генерируется один раз при первом запуске и хранится в localStorage.
     */
    getFingerprint() {
        let fpr = localStorage.getItem('device_fingerprint');
        if (!fpr) {
            // crypto.getRandomValues() может быть undefined на HTTP (non-HTTPS).
            // Пробуем secure API, fallback на Math.random() для localhost/dev.
            try {
                const arr = new Uint8Array(16);
                crypto.getRandomValues(arr);
                fpr = Array.from(arr).map(b => b.toString(16).padStart(2, '0')).join('');
            } catch (_e) {
                // Fallback для небезопасного контекста (HTTP)
                fpr = Array.from({ length: 32 }, () =>
                    Math.floor(Math.random() * 16).toString(16)
                ).join('');
            }
            localStorage.setItem('device_fingerprint', fpr);
        }
        return fpr;
    }

    /**
     * Очищает fingerprint (при выходе или детекте кражи).
     * При следующем входе сгенерируется новый.
     */
    clearFingerprint() {
        localStorage.removeItem('device_fingerprint');
    }

    // ── Token management ───────────────────────────────────────────

    isAuthenticated() {
        const tokens = this.getTokens();
        return !!(tokens.access || tokens.refresh);
    }

    getTokens() {
        return {
            access: localStorage.getItem('access_token'),
            refresh: localStorage.getItem('refresh_token')
        };
    }

    setTokens(access, refresh) {
        if (access) localStorage.setItem('access_token', access);
        if (refresh) localStorage.setItem('refresh_token', refresh);
    }

    clearTokens() {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
    }

    expireSession(theftDetected = false) {
        this.clearTokens();
        this.clearFingerprint();
        if (theftDetected) {
            sessionStorage.setItem('token_theft', '1');
        } else {
            sessionStorage.setItem('session_expired', '1');
        }
        window.location.href = '/accounts/login/';
    }

    // ── HTTP requests ──────────────────────────────────────────────

    async request(endpoint, options = {}) {
        const url = `${this.baseUrl}${endpoint}`;
        const headers = { ...options.headers };
        if (!(options.body instanceof FormData) && !headers['Content-Type']) {
            headers['Content-Type'] = 'application/json';
        }

        const tokens = this.getTokens();
        if (tokens.access && !options.noAuth) {
            headers['Authorization'] = `Bearer ${tokens.access}`;
        }

        // Таймаут: fetch() без сигнала висит вечно, если сервер принял
        // соединение, но не отвечает (или сеть зависла). Обрываем сами.
        // Форма-загрузки (фото/файлы) могут идти дольше — опция options.timeout.
        const timeout = options.timeout ?? 30000;
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeout);

        const config = {
            ...options,
            headers,
            signal: options.signal || controller.signal,
        };

        try {
            let response = await fetch(url, config);

            // Автоматическое обновление токена при 401
            if (response.status === 401 && tokens.refresh && !options.isRetry) {
                const newAccess = await this.refreshToken(tokens.refresh);
                if (newAccess) {
                    headers['Authorization'] = `Bearer ${newAccess}`;
                    config.isRetry = true;
                    response = await fetch(url, config);
                } else {
                    // Проверяем, не кража ли это токена
                    const errorBody = await response.clone().json().catch(() => ({}));
                    this.expireSession(!!errorBody.token_theft);
                    throw new Error('Authentication required');
                }
            }

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw { status: response.status, data: errorData };
            }

            // 204 No Content и 205 Reset Content приходят с пустым телом —
            // не пытаемся разбирать JSON (иначе SyntaxError в консоли).
            if (response.status === 204 || response.status === 205) {
                return null;
            }

            return response.json();
        } catch (e) {
            if (e.name === 'AbortError') {
                throw { status: 0, data: { detail: 'Request timed out' } };
            }
            throw e;
        } finally {
            clearTimeout(timer);
        }
    }

    // ── Token refresh with fingerprint ─────────────────────────────

    async refreshToken(refresh) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 15000);
        try {
            const fingerprint = this.getFingerprint();
            const response = await fetch(`${this.baseUrl}/accounts/token/refresh/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh, fingerprint }),
                signal: controller.signal,
            });

            if (response.ok) {
                const data = await response.json();
                this.setTokens(data.access, data.refresh || refresh);
                return data.access;
            }

            // Проверяем детект кражи
            const errorBody = await response.clone().json().catch(() => ({}));
            if (errorBody.token_theft) {
                this.expireSession(true);
                return null;
            }
        } catch (error) {
            console.error('Token refresh failed', error);
        } finally {
            clearTimeout(timer);
        }
        return null;
    }

    // ── Authentication ─────────────────────────────────────────────

    async login(username, password) {
        const fingerprint = this.getFingerprint();
        const data = await this.request('/accounts/login/', {
            method: 'POST',
            body: JSON.stringify({ username, password, fingerprint }),
            noAuth: true
        });
        this.setTokens(data.tokens.access, data.tokens.refresh);
        return data.user;
    }

    async logout() {
        const tokens = this.getTokens();
        if (tokens.refresh) {
            try {
                await this.request('/accounts/logout/', {
                    method: 'POST',
                    body: JSON.stringify({ refresh: tokens.refresh })
                });
            } catch (e) {
                console.error(e);
            }
        }
        this.clearTokens();
        this.clearFingerprint();
        window.location.href = '/accounts/login/';
    }

    async getMe() {
        return this.request('/accounts/me/');
    }
}

const api = new APIClient();
window.api = api;   