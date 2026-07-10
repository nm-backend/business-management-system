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
            this.renderNotFound(path);
            return;
        }

        this.appElement.innerHTML = '<div class="loading" data-i18n="common.loading">Loading...</div>';
        window.i18n.applyTranslations();

        try {
            await component.render(this.appElement);
            window.i18n.applyTranslations();
        } catch (e) {
            console.error('Error rendering route:', e);
            this.appElement.innerHTML = '<div class="card route-error"><h1>Something went wrong</h1><p>We could not load this page.</p></div>';
            window.i18n.applyTranslations();
        }
    }

    renderNotFound(path) {
        this.appElement.innerHTML = `<div class="card route-error"><p class="eyebrow">404</p><h1>Page not found</h1><p>The route <strong>${path}</strong> does not exist.</p><a class="btn btn-primary" href="#/">Return to dashboard</a></div>`;
    }

    navigate(path) {
        window.location.hash = path;
    }
}

window.router = new Router();
