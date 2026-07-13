/**
 * App bootstrap: авторизация, роль, навигация (сайдбар для десктопа,
 * нижнее меню для мобильных), маршруты SPA.
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

    // Показываем «хром» приложения (top-bar + sidebar/bottom-nav через CSS).
    document.body.classList.add('authenticated');
    setupSidebar(user);

    // Платформенный супер-администратор управляет только компаниями.
    if (user.is_superadmin) {
        document.getElementById('notifications-btn').style.display = 'none';
        window.router.addRoute('/', window.CompaniesComponent);
        window.router.addRoute('/companies', window.CompaniesComponent);
        window.router.addRoute('/settings', window.SettingsComponent);
        window.router.handleRoute();
        return;
    }

    // Мобильное нижнее меню по ролям: работник вместо клиентов видит задачи.
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

/**
 * Заполняет десктопный сайдбар: имя/роль пользователя, выход,
 * и скрывает пункты, недоступные роли.
 */
function setupSidebar(user) {
    const userBox = document.getElementById('sidebar-user');
    if (userBox) {
        const roleLabel = window.i18n ? window.i18n.translate('roles.' + user.role) : user.role;
        userBox.innerHTML = `${escapeText(user.full_name || user.username)}<br><span class="text-muted text-sm">${escapeText(roleLabel)}${user.company_name ? ' · ' + escapeText(user.company_name) : ''}</span>`;
    }
    const logoutBtn = document.getElementById('sidebar-logout');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', async () => {
            if (!window.confirmation || await window.confirmation.confirm(
                window.i18n.translate('auth.logout_confirm'), window.i18n.translate('auth.logout'))) {
                window.api.logout();
            }
        });
    }

    // Видимость пунктов сайдбара по роли (data-role: staff | staff-worker | owner | superadmin).
    document.querySelectorAll('.app-sidebar .sidebar-link').forEach((link) => {
        const role = link.dataset.role;
        let show = true;
        if (user.is_superadmin) {
            show = ['companies', 'settings'].includes(link.dataset.nav);
        } else if (link.dataset.nav === 'companies') {
            show = false;
        } else if (role === 'owner') {
            show = user.is_owner;
        } else if (role === 'staff') {
            show = user.is_owner || user.is_admin;
        }
        link.style.display = show ? '' : 'none';
    });
}

function escapeText(value) {
    const div = document.createElement('div');
    div.textContent = value ?? '';
    return div.innerHTML;
}

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
