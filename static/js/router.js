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

        // Подсветка активного пункта в обоих меню (сайдбар + нижнее) по data-nav.
        let navKey = 'dashboard';
        if (path.startsWith('/orders')) navKey = 'orders';
        if (path.startsWith('/warehouse')) navKey = 'warehouse';
        if (path.startsWith('/finished-products')) navKey = 'warehouse';
        if (path.startsWith('/clients')) navKey = 'clients';
        if (path.startsWith('/production')) navKey = 'production';
        if (path.startsWith('/finance')) navKey = 'finance';
        if (path.startsWith('/messages')) navKey = 'messages';
        if (path.startsWith('/companies')) navKey = 'companies';
        if (path.startsWith('/settings')) navKey = 'settings';
        // На мобильном отдельного пункта нет — часть страниц подсвечивают «Кўпроқ».
        const bottomKey = ['finance', 'messages', 'companies'].includes(navKey) ? 'settings' : navKey;
        document.querySelectorAll('.sidebar-link, .nav-item').forEach((el) => {
            const key = el.classList.contains('sidebar-link') ? navKey : bottomKey;
            el.classList.toggle('active', el.dataset.nav === key);
        });

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
