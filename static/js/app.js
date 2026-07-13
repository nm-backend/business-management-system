/**
 * App bootstrap: авторизация, роль, навигация, маршруты SPA.
 */
document.addEventListener('DOMContentLoaded', async () => {
    if (!window.api.isAuthenticated()) {
        window.location.href = '/accounts/login/';
        return;
    }

    let user;
    try {
        user = await window.api.getMe();
    } catch (e) {
        return; // APIClient сам уводит на логин при истёкшей сессии
    }
    window.currentUser = user;

    document.getElementById('app-top-bar').style.display = 'flex';

    // Платформенный супер-администратор управляет только компаниями.
    if (user.is_superadmin) {
        document.getElementById('app-bottom-nav').style.display = 'none';
        document.getElementById('notifications-btn').style.display = 'none';
        window.router.addRoute('/', window.CompaniesComponent);
        window.router.addRoute('/companies', window.CompaniesComponent);
        window.router.addRoute('/settings', window.SettingsComponent);
        window.router.handleRoute();
        return;
    }

    document.getElementById('app-bottom-nav').style.display = 'flex';

    // Меню по ролям: работник вместо клиентов видит свои задачи.
    if (user.is_worker) {
        document.getElementById('nav-clients').style.display = 'none';
        document.getElementById('nav-production').style.display = 'flex';
    }

    document.getElementById('notifications-btn').addEventListener('click', () => {
        window.location.hash = '#/messages?tab=notifications';
    });

    // Маршруты SPA
    window.router.addRoute('/', window.DashboardComponent);
    window.router.addRoute('/warehouse', window.WarehouseComponent);
    window.router.addRoute('/finished-products', window.FinishedProductsComponent);
    window.router.addRoute('/clients', window.ClientsComponent);
    window.router.addRoute('/orders', window.OrdersComponent);
    window.router.addRoute('/production', window.ProductionComponent);
    window.router.addRoute('/finance', window.FinanceComponent);
    window.router.addRoute('/messages', window.MessagesComponent);
    window.router.addRoute('/settings', window.SettingsComponent);

    window.router.handleRoute();
    refreshNotificationBadge();
    setInterval(refreshNotificationBadge, 60000);
});

async function refreshNotificationBadge() {
    try {
        const response = await window.api.request('/messaging/notifications/?is_read=false');
        const count = response.count ?? (response.results || response).length;
        const badge = document.getElementById('notif-badge');
        badge.style.display = count > 0 ? 'flex' : 'none';
        badge.textContent = count > 99 ? '99+' : count;
    } catch (e) {
        /* не критично */
    }
}
window.refreshNotificationBadge = refreshNotificationBadge;
