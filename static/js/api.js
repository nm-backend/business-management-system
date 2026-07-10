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
            headers
        };

        let response = await fetch(url, config);

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
            const response = await fetch(`${this.baseUrl}/accounts/token/refresh/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh })
            });
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

const api = new APIClient();
window.api = api;
