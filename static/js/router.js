/**
 * Router - hash-based роутер для навигации между страницами.
 * Отображает компоненты в #app-content по URL hash.
 */
class Router {
    constructor() {
        this.routes = {};
        this.appElement = document.getElementById('app-content');

        window.addEventListener('hashchange', () => this.handleRoute());
    }

    addRoute(path, component) {
        this.routes[path] = component;
    }

    async handleRoute() {
        const path = window.location.hash.slice(1) || '/';
        let component = this.routes[path];

        if (!component) {
            // Если маршрут не найден, показываем главную страницу
            component = this.routes['/'];
        }

        this.appElement.innerHTML = '<div class="loading" data-i18n="common.loading">Loading...</div>';
        window.i18n.applyTranslations();

        try {
            await component.render(this.appElement);
            window.i18n.applyTranslations();
        } catch (e) {
            console.error('Error rendering route:', e);
            this.appElement.innerHTML = '<div class="alert alert-danger" data-i18n="common.error">Error</div>';
            window.i18n.applyTranslations();
        }
    }

    navigate(path) {
        window.location.hash = path;
    }
}

window.router = new Router();
