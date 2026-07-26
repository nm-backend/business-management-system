/**
 * APIClient - клиент для взаимодействия с Django REST API.
 *
 * Управляет JWT токенами и автоматическим обновлением при истечении срока.
 */
class APIClient {
    constructor() {
        this.baseUrl = '/api/v1';
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

    expireSession() {
        this.clearTokens();
        sessionStorage.setItem('session_expired', '1');
        window.location.href = '/accounts/login/';
    }

    async request(endpoint, options = {}) {
        // Add fetch timeout (30s default)
        const timeout = options.timeout || 30000;
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeout);

        const url = `${this.baseUrl}${endpoint}`;
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers
        };

        const tokens = this.getTokens();
        if (tokens.access && !options.noAuth) {
            headers['Authorization'] = `Bearer ${tokens.access}`;
        }

        const config = {
            ...options,
            headers,
            signal: controller.signal
        };

        // Remove timeout from options so it doesn't get sent to fetch
        delete config.timeout;

        let response;
        try {
            response = await fetch(url, config);
        } catch (e) {
            clearTimeout(timeoutId);
            if (e.name === 'AbortError') {
                if (window.toast) window.toast.error('Request timed out');
                throw { status: 0, data: { detail: 'Request timed out' } };
            }
            throw e;
        }
        clearTimeout(timeoutId);

        // Автоматическое обновление токена при 401
        if (response.status === 401 && tokens.refresh && !options.isRetry) {
            const newAccess = await this.refreshToken(tokens.refresh);
            if (newAccess) {
                headers['Authorization'] = `Bearer ${newAccess}`;
                config.isRetry = true;
                response = await fetch(url, config);
            } else {
                this.expireSession();
                throw new Error('Authentication required');
            }
        }

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            if (window.toast && response.status !== 401) {
                window.toast.error(errorData.detail || 'Request failed');
            }
            throw { status: response.status, data: errorData };
        }

        if (response.status === 204) {
            return null;
        }

        return response.json();
    }

    async refreshToken(refresh) {
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 10000);
            const response = await fetch(`${this.baseUrl}/accounts/token/refresh/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh }),
                signal: controller.signal
            });
            clearTimeout(timeoutId);
            if (response.ok) {
                const data = await response.json();
                this.setTokens(data.access, data.refresh || refresh);
                return data.access;
            }
        } catch (error) {
            console.error('Token refresh failed', error);
        }
        return null;
    }

    async login(username, password) {
        const data = await this.request('/accounts/login/', {
            method: 'POST',
            body: JSON.stringify({ username, password }),
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
        window.location.href = '/accounts/login/';
    }

    isAuthenticated() {
        return !!this.getTokens().access;
    }

    async getMe() {
        return this.request('/accounts/me/');
    }
}

/**
 * Экранирует HTML-опасные символы для защиты от XSS.
 * Используйте это при вставке данных из API в innerHTML.
 *
 * @param {string} str - Пользовательский ввод или данные из API
 * @returns {string} - Безопасная строка
 */
function escapeHtml(str) {
    if (str == null) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}

/**
 * Экранирует все строковые поля в объекте для безопасного рендеринга.
 *
 * @param {Object} obj - Объект с данными
 * @returns {Object} - Новый объект с экранированными строками
 */
function escapeObject(obj) {
    if (!obj || typeof obj !== 'object') return obj;
    if (Array.isArray(obj)) return obj.map(escapeObject);
    const result = {};
    for (const [key, value] of Object.entries(obj)) {
        result[key] = typeof value === 'string' ? escapeHtml(value) : escapeObject(value);
    }
    return result;
}

window.escapeHtml = escapeHtml;
window.escapeObject = escapeObject;

const api = new APIClient();
window.api = api;
