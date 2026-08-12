/**
 * Hash-роутер SPA. Поддерживает query-часть: #/messages?tab=notifications.
 */
class Router {
    constructor() {
        this.routes = {};
        this.query = new URLSearchParams();
        // «Назад» при открытом окне: ui.modal() кладёт в историю свою запись с
        // ТЕМ ЖЕ адресом, поэтому здесь приходит popstate без hashchange —
        // просто закрываем верхнее окно и никуда не уходим.
        window.addEventListener('popstate', () => {
            if (!window.ui || !window.ui.closeTopModal) return;
            // Своё же history.back() из closeModal возвращается сюда с задержкой.
            // Если за это время открыли следующее окно (карточка -> форма), этот
            // popstate закрыл бы именно его: окно появлялось и тут же исчезало.
            if (window.ui.consumeHistoryRelease && window.ui.consumeHistoryRelease()) return;
            window.ui.closeTopModal();
        });

        // Смена адреса (клик по меню): окно не должно остаться над новой страницей.
        window.addEventListener('hashchange', () => {
            if (window.ui && window.ui.closeTopModal) {
                while (window.ui.closeTopModal()) { /* закрываем все открытые */ }
            }
            this.handleRoute();
        });

        // Escape — привычный способ закрыть окно с клавиатуры.
        document.addEventListener('keydown', (e) => {
            if (e.key !== 'Escape') return;
            const modals = document.querySelectorAll('.modal');
            if (modals.length && window.ui) window.ui.closeModal(modals[modals.length - 1]);
        });
    }

    addRoute(path, component) {
        this.routes[path] = component;
    }

    setActiveNav(navKey, bottomKey) {
        document.querySelectorAll('.sidebar-link, .nav-item').forEach((el) => {
            const isSidebar = el.classList.contains('sidebar-link');
            const key = isSidebar ? navKey : bottomKey;
            const active = el.dataset.nav === key;
            el.classList.toggle('active', active);
            if (active) {
                el.setAttribute('aria-current', 'page');
            } else {
                el.removeAttribute('aria-current');
            }
        });
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
        if (path.startsWith('/orders/kanban')) navKey = 'kanban';
        if (path.startsWith('/warehouse')) navKey = 'warehouse';
        if (path.startsWith('/finished-products')) navKey = 'warehouse';
        if (path.startsWith('/clients')) navKey = 'clients';
        if (path.startsWith('/production')) navKey = 'production';
        if (path.startsWith('/finance')) navKey = 'finance';
        if (path.startsWith('/messages')) navKey = 'messages';
        if (path.startsWith('/companies')) navKey = 'companies';
        if (path.startsWith('/audit')) navKey = 'audit';
        if (path.startsWith('/settings')) navKey = 'settings';
        // На мобильном отдельного пункта нет — часть страниц подсвечивают «Кўпроқ».
        const bottomKey = ['finance', 'messages', 'companies'].includes(navKey) ? 'settings' : navKey;
        this.setActiveNav(navKey, bottomKey);

        appElement.innerHTML = '<div class="list-state list-state-loading"><span class="spinner"></span><span data-i18n="common.loading">…</span></div>';
        window.i18n.applyTranslations();

        try {
            await component.render(appElement);
            window.i18n.applyTranslations();
            const titleText = document.getElementById('page-title')?.textContent?.trim();
            if (titleText) {
                document.title = `${titleText} · SkladPro`;
            }
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
                <p><strong>${window.ui.escape(path)}</strong></p>
                <a class="btn btn-primary btn-sm" href="#/" data-i18n="nav.dashboard">Бош панел</a>
            </div>`;
        window.i18n.applyTranslations();
        document.title = `${window.ui.t('common.page_not_found')} · SkladPro`;
    }

    /**
     * Переход по маршруту.
     *
     * Закрывать открытое окно перед вызовом НЕ нужно: обработчик hashchange
     * выше закрывает все окна сам. Вызов ui.closeModal() перед navigate()
     * наоборот ломает переход — его history.back() возвращает адрес назад
     * (воспроизведено: «Заказы» в карточке клиента оставляли на клиентах).
     */
    navigate(path) {
        window.location.hash = path;
    }
}

window.router = new Router();
