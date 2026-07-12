/**
 * Hash-роутер SPA. Поддерживает query-часть: #/messages?tab=notifications.
 */
class Router {
    constructor() {
        this.routes = {};
        this.query = new URLSearchParams();
        window.addEventListener('hashchange', () => this.handleRoute());
    }

    addRoute(path, component) {
        this.routes[path] = component;
    }

    async handleRoute() {
        const appElement = document.getElementById('app-content');
        const hash = window.location.hash.slice(1) || '/';
        const [path, queryString] = hash.split('?');
        this.query = new URLSearchParams(queryString || '');

        const component = this.routes[path];
        if (!component) {
            this.renderNotFound(appElement, path);
            return;
        }

        // Подсветка активного пункта нижнего меню
        document.querySelectorAll('.nav-item').forEach((el) => el.classList.remove('active'));
        let navId = 'nav-dashboard';
        if (path.startsWith('/orders')) navId = 'nav-orders';
        if (path.startsWith('/warehouse') || path.startsWith('/finished-products')) navId = 'nav-warehouse';
        if (path.startsWith('/clients')) navId = 'nav-clients';
        if (path.startsWith('/production')) navId = 'nav-production';
        if (path.startsWith('/settings') || path.startsWith('/finance') || path.startsWith('/messages')) navId = 'nav-settings';
        const activeNav = document.getElementById(navId);
        if (activeNav) activeNav.classList.add('active');

        appElement.innerHTML = '<div class="list-state list-state-loading"><span class="spinner"></span><span data-i18n="common.loading">Юкланмоқда...</span></div>';
        window.i18n.applyTranslations();

        try {
            await component.render(appElement);
            window.i18n.applyTranslations();
        } catch (e) {
            console.error('Error rendering route:', e);
            appElement.innerHTML = `
                <div class="card route-error">
                    <h1 data-i18n="common.error">Хатолик</h1>
                    <p data-i18n="common.page_load_error">Саҳифани юклаб бўлмади.</p>
                </div>`;
            window.i18n.applyTranslations();
        }
    }

    renderNotFound(appElement, path) {
        appElement.innerHTML = `
            <div class="card route-error">
                <p class="eyebrow">404</p>
                <h1 data-i18n="common.page_not_found">Саҳифа топилмади</h1>
                <p><strong>${path}</strong></p>
                <a class="btn btn-primary btn-sm" href="#/" data-i18n="nav.dashboard">Бош панел</a>
            </div>`;
        window.i18n.applyTranslations();
    }

    navigate(path) {
        window.location.hash = path;
    }
}

window.router = new Router();
