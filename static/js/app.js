/**
 * App bootstrap: авторизация, роль, навигация (сайдбар для десктопа,
 * нижнее меню для мобильных), маршруты SPA, WebSocket уведомления.
 *
 * SaaS GATE: пользователь компании с неактивной подпиской (истёкшей,
 * замороженной или отменённой) видит только ограниченный экран
 * «Подписка истекла» — бизнес-маршруты и real-time соединение не запускаются.
 * Супер-админ (company=None) и сотрудники активных компаний не затрагиваются.
 */

// Глобальные ловушки: непойманные ошибки не должны молча умирать в консоли —
// в проде это единственный способ заметить их из UI (тост + console).
window.addEventListener('error', (event) => {
    console.error('Uncaught error:', event.error || event.message);
    try {
        window.toast.error(window.ui?.t('common.error') || 'Ошибка');
    } catch (e) { /* toast недоступен на странице логина */ }
});
window.addEventListener('unhandledrejection', (event) => {
    console.error('Unhandled rejection:', event.reason);
    try {
        window.toast.error(window.ui?.t('common.error') || 'Ошибка');
    } catch (e) { /* toast недоступен на странице логина */ }
});

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
    // Флаг каскадной перезагрузки из api.js (403 подписки) сбрасываем всегда:
    // компания могла быть разморожена, пока шла перезагрузка.
    sessionStorage.removeItem('sub_blocked_reload');

    // SaaS gate: компания с неактивной подпиской (истёкшей/замороженной/
    // отменённой) видит только ограниченный экран «Подписка истекла».
    // Льготный период (grace) НЕ блокирует: бизнес продолжает работать,
    // сверху показывается предупреждающий баннер с датой блокировки.
    // Супер-админ (company=None) и сотрудники активных компаний проходят дальше.
    const blockedStatuses = ['expired', 'frozen', 'cancelled'];
    if (!user.is_superadmin && user.subscription_status && blockedStatuses.includes(user.subscription_status)) {
        showSubscriptionBlockedScreen(user);
        return;
    }
    if (!user.is_superadmin && user.subscription_status === 'grace') {
        showGraceBanner(user);
    }

    // Замороженная подписка: вместо «хрома» приложения — экран «Подписка истекла».
    // Вход, профиль и статус подписки доступны (whitelist gate), бизнес-функции — нет.
    if (user.subscription && user.subscription.is_frozen) {
        showFrozenScreen(user);
        return;
    }

    // Показываем «хром» приложения (top-bar + sidebar/bottom-nav через CSS).
    document.body.classList.add('authenticated');
    setupSidebar(user);

    // Платформенный супер-администратор управляет платформой (компании, подписки, аудит).
    // Бизнес-данные (заказы, склад, производство, клиенты, финансы) ему недоступны.
    if (user.is_superadmin) {
        document.getElementById('notifications-btn').addEventListener('click', () => {
            window.location.hash = '#/messages?tab=notifications';
        });
        // Скрываем пункты навигации, недоступные для superadmin
        // (сайдбар фильтруется в setupSidebar через data-role, bottom-nav здесь).
        ['nav-orders', 'nav-warehouse', 'nav-clients', 'nav-production', 'nav-finance'].forEach(function(id) {
            let el = document.getElementById(id);
            if (el) el.style.display = 'none';
        });
        // SuperAdmin routes: только платформенные
        window.router.addRoute('/', window.PlatformDashboardComponent);
        window.router.addRoute('/companies', window.CompaniesComponent);
        window.router.addRoute('/messages', window.MessagesComponent);
        window.router.addRoute('/settings', window.SettingsComponent);
        // Блокируем прямой доступ к бизнес-маршрутам
        ['/orders', '/warehouse', '/finished-products', '/production', '/clients', '/finance', '/subscription', '/audit', '/backup'].forEach(function(path) {
            window.router.addRoute(path, function(container) {
                container.innerHTML = '<div class="card route-error"><p class="eyebrow">403</p><h1 data-i18n="common.forbidden">Доступ запрещён</h1><p data-i18n="superadmin.no_business_access"></p><a class="btn btn-primary btn-sm" href="#/" data-i18n="nav.dashboard">Платформа</a></div>';
                window.i18n.applyTranslations();
            });
        });
        window.router.handleRoute();

        if (localStorage.getItem('theme') === 'dark') {
            document.body.classList.add('theme-dark');
        }
        registerServiceWorker();
        refreshNotificationBadge();
        window.notificationBadgeTimer = setInterval(refreshNotificationBadge, 60000);
        return;
    }

    document.getElementById('notifications-btn').addEventListener('click', () => {
        window.location.hash = '#/messages?tab=notifications';
    });

    // Ensure the nav state is stable before route processing.
    document.querySelectorAll('#app-bottom-nav .nav-item, .sidebar-link').forEach((link) => {
        if (!link.dataset.nav) return;
        link.classList.remove('active');
        link.removeAttribute('aria-current');
    });

    // Маршруты SPA
    window.router.addRoute('/', window.DashboardComponent);
    window.router.addRoute('/warehouse', window.WarehouseComponent);
    window.router.addRoute('/finished-products', window.FinishedProductsComponent);
    window.router.addRoute('/clients', window.ClientsComponent);
    window.router.addRoute('/orders', window.OrdersComponent);
    window.router.addRoute('/orders/kanban', window.KanbanComponent);
    window.router.addRoute('/production', window.ProductionComponent);
    window.router.addRoute('/finance', window.FinanceComponent);
    window.router.addRoute('/messages', window.MessagesComponent);
    window.router.addRoute('/subscription', window.SubscriptionComponent);
    window.router.addRoute('/settings', window.SettingsComponent);
    window.router.addRoute('/audit', window.AuditComponent);
    window.router.addRoute('/backup', window.SettingsComponent);

    window.router.handleRoute();
    setupBottomNav(user);

    // Загрузка тёмной темы
    if (localStorage.getItem('theme') === 'dark') {
        document.body.classList.add('theme-dark');
    }

    // Регистрация Service Worker
    registerServiceWorker();

    // Real-time уведомления: единое соединение через тикет (ChatSocket).
    // Раньше здесь жил connectWebSocket() с access-токеном в query-строке:
    // после перевода бэкенда на тикеты он умирал с 4401 и переподключался
    // по кругу, капая токеном в логи прокси. Соединение теперь одно.
    window.chatSocket.setBroadcastHandler(onRealtimeMessage);
    window.chatSocket.connect();
    refreshNotificationBadge();
    // Таймер храним в window: api.logout() очищает его, чтобы бейдж не
    // долбил неавторизованные запросы после выхода.
    window.notificationBadgeTimer = setInterval(refreshNotificationBadge, 60000);
});

/**
 * Ограниченный экран для компании с неактивной подпиской.
 *
 * Пользователь замороженной/истёкшей компании НЕ попадает в тупик: он может
 * войти, увидеть дату окончания, текущий статус, что нужно сделать для
 * продления, и выйти из системы. Бизнес-навигация и сокеты не запускаются.
 */
function showSubscriptionBlockedScreen(user) {
    // Хром бизнес-приложения скрываем: остаётся только ограниченный экран.
    const sidebar = document.getElementById('app-sidebar');
    const bottomNav = document.getElementById('app-bottom-nav');
    const notifications = document.getElementById('notifications-btn');
    if (sidebar) sidebar.style.display = 'none';
    if (bottomNav) bottomNav.style.display = 'none';
    if (notifications) notifications.style.display = 'none';

    const frozen = user.subscription_status === 'frozen';
    const titleKey = frozen ? 'subscription.frozen_title' : 'subscription.expired_title';
    const textKey = frozen ? 'subscription.frozen_text' : 'subscription.expired_text';

    document.getElementById('page-title').setAttribute('data-i18n', titleKey);

    const appElement = document.getElementById('app-content');
    appElement.innerHTML = `
        <div class="card subscription-blocked" style="max-width:520px;margin:24px auto;padding:24px;">
            <div style="text-align:center;font-size:44px;margin-bottom:8px;">${frozen ? '❄️' : '⏳'}</div>
            <h2 style="text-align:center;" data-i18n="${titleKey}"></h2>
            <p class="text-muted" data-i18n="${textKey}"></p>

            <div class="list-group" style="box-shadow:none;border:1px solid var(--border);margin:16px 0;">
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm text-muted" data-i18n="subscription.current_status"></span>
                    <span class="badge ${frozen ? 'badge-progress' : 'badge-cancel'}">${window.ui.escape(user.subscription_status_display || user.subscription_status || '')}</span>
                </div>
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm text-muted" data-i18n="subscription.end_date"></span>
                    <span class="text-sm font-bold">${window.ui.datetime(user.subscription_end)}</span>
                </div>
            </div>

            <div class="section-title" data-i18n="subscription.what_to_do"></div>
            <p class="text-muted" data-i18n="subscription.renew_instructions"></p>

            <button class="btn btn-primary btn-block" id="sub-blocked-request" style="margin-top:16px;" data-i18n="subscription.request_renewal"></button>
            <button class="btn btn-secondary btn-block" id="sub-blocked-logout" style="margin-top:8px;" data-i18n="auth.logout"></button>
        </div>
    `;

    // Кнопка «Запросить продление»: замороженная компания не должна
    // заводить владельца в тупик — запрос уходит суперадмину в колокольчик
    // (эндпоинт обходит SaaS-гейт: это платформенный контур, не бизнес-данные).
    const requestBtn = appElement.querySelector('#sub-blocked-request');
    if (requestBtn) {
        requestBtn.addEventListener('click', async () => {
            try {
                const resp = await window.api.request('/companies/my-subscription/request-renewal/', {
                    method: 'POST', body: JSON.stringify({}),
                });
                window.toast.success(window.ui.t(resp.created ? 'subscription.request_sent' : 'subscription.request_already'));
                if (resp.created) requestBtn.setAttribute('disabled', '');
            } catch (e) {
                window.toast.error(window.ui.errorText ? window.ui.errorText(e) : window.ui.t('common.error'));
            }
        });
    }
    appElement.querySelector('#sub-blocked-logout').addEventListener('click', () => {
        window.api.logout();
    });

    window.i18n.applyTranslations();
    document.title = `${window.ui.t(titleKey)} · SkladPro`;
}

/**
 * Предупреждающий баннер для компании в льготном периоде (grace).
 *
 * Бизнес работает, но срок подписки уже истёк: баннер висит над контентом
 * со ссылкой на страницу «Подписка», пока льготный период не закончился.
 */
function showGraceBanner(user) {
    if (document.getElementById('grace-banner')) return;
    const main = document.querySelector('main.main-content');
    const app = document.getElementById('app-content');
    if (!main || !app) return;
    const banner = document.createElement('div');
    banner.id = 'grace-banner';
    banner.className = 'alert-box';
    banner.style.cssText = 'margin:0 0 12px;padding:12px 14px;display:flex;align-items:center;gap:10px;justify-content:space-between;flex-wrap:wrap;border-color:var(--warning,#f59e0b);';
    const deadline = user.subscription_grace_end
        ? window.ui.datetime(user.subscription_grace_end)
        : '';
    banner.innerHTML = `
        <span style="display:inline-flex;align-items:center;gap:8px;">
            ⏳ <strong data-i18n="subscription.grace_title"></strong>
            <span class="text-sm text-muted">${deadline ? ' · ' + window.ui.escape(window.ui.t('subscription.grace_deadline')) + ': ' + deadline : ''}</span>
        </span>
        <button class="btn btn-primary btn-sm" id="grace-banner-go" style="width:auto;">
            <span data-i18n="subscription.request_renewal"></span>
        </button>
    `;
    // Баннер живёт НАД #app-content: роутер переписывает innerHTML контента
    // при каждой навигации, а предупреждение о льготном периоде должно
    // оставаться видимым на любой странице, пока период не закончился.
    main.insertBefore(banner, app);
    banner.querySelector('#grace-banner-go').addEventListener('click', () => {
        window.location.hash = '#/subscription';
    });
    window.i18n.applyTranslations();
}

/**
 * Глобальный обработчик real-time событий (вызывается на любой странице).
 * Активный чат обрабатывает сообщения сам через свой handler; здесь — бейдж,
 * звук, SW-уведомление и тост для сообщений, пришедших мимо открытого чата.
 */
function onRealtimeMessage(msg) {
    if (!msg || msg.sender === undefined) return;
    refreshNotificationBadge();
    playNotificationSound();
    sendSWNotification({
        title: `✉️ ${msg.sender_name || window.ui?.t('notifications.message_default') || 'Сообщение'}`,
        body: (msg.content || '').slice(0, 120),
        tag: 'chat_message',
        data: { url: '#/messages' },
    });
    // Тост — только для чужих сообщений и когда чат неактивен: в чате
    // сообщение уже вставлено в ленту, тост продублировал бы его.
    const mine = window.currentUser && msg.sender === window.currentUser.id;
    if (!mine && !window.chatSocket.handler) {
        window.toast.info(`✉️ ${msg.sender_name}: ${(msg.content || '').slice(0, 60)}`);
    }
}

/** ── Service Worker registration ── */
let swRegistration = null;

async function registerServiceWorker() {
    if (!('serviceWorker' in navigator)) return;
    try {
        swRegistration = await navigator.serviceWorker.register('/sw.js');
    } catch (e) {
        // Service Worker not supported or blocked
    }
}

/** Отправляет сообщение Service Worker'у для показа системного уведомления. */
function sendSWNotification({ title, body, tag, data } = {}) {
    if (!swRegistration || !swRegistration.active) return;
    try {
        swRegistration.active.postMessage({
            type: 'show_notification',
            title,
            body,
            tag: tag || 'notification',
            data: data || {},
        });
    } catch (e) {
        // SW not ready yet
    }
}

/** Запросить разрешение на push-уведомления. */
async function requestNotificationPermission() {
    if (!('Notification' in window)) return 'unsupported';
    if (Notification.permission === 'granted') return 'granted';
    if (Notification.permission === 'denied') return 'denied';
    const result = await Notification.requestPermission();
    if (result === 'granted' && swRegistration) {
        // Тест-уведомление
        sendSWNotification({
            title: 'SkladPro.Nod',
            body: window.i18n.translate('notifications.enabled'),
            tag: 'welcome',
        });
        // Подписываемся на VAPID push
        subscribeToPush();
    }
    return result;
}

/** Подписка на VAPID push-уведомления (серверные, работают когда вкладка закрыта). */
async function subscribeToPush(retries = 5) {
    if (!('PushManager' in window)) return;
    // Ждём регистрацию SW (может ещё не завершиться)
    for (let i = 0; i < retries; i++) {
        if (swRegistration) break;
        await new Promise((r) => setTimeout(r, 500));
    }
    if (!swRegistration) return;
    try {
        const me = await window.api.request('/accounts/me/');
        if (!me.vapid_public_key) return;

        const sub = await swRegistration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlB64ToUint8Array(me.vapid_public_key),
        });

        const subData = sub.toJSON();
        await window.api.request('/accounts/push/subscribe/', {
            method: 'POST',
            body: JSON.stringify({
                endpoint: subData.endpoint,
                keys: subData.keys,
            }),
        });
    } catch (e) {
        console.warn('Push subscribe failed:', e);
    }
}

/** Отписка от VAPID push-уведомлений. */
async function unsubscribeFromPush() {
    if (!swRegistration || !('PushManager' in window)) return;
    try {
        const sub = await swRegistration.pushManager.getSubscription();
        if (sub) {
            const endpoint = sub.endpoint;
            await sub.unsubscribe();
            // Уведомляем сервер
            await window.api.request('/accounts/push/subscribe/', {
                method: 'DELETE',
                body: JSON.stringify({ endpoint }),
            });
        }
    } catch (e) {
        console.warn('Push unsubscribe failed:', e);
    }
}
window.unsubscribeFromPush = unsubscribeFromPush;

/** Преобразует base64 VAPID ключ в Uint8Array для Push API. */
function urlB64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const rawData = atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; ++i) {
        outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
}
window.requestNotificationPermission = requestNotificationPermission;

/** Singleton AudioContext — не создаём новый при каждом уведомлении. */
let _notifCtx = null;
function playNotificationSound() {
    try {
        if (!_notifCtx) {
            _notifCtx = new (window.AudioContext || window.webkitAudioContext)();
        }
        if (_notifCtx.state === 'suspended') {
            _notifCtx.resume();
        }
        const osc = _notifCtx.createOscillator();
        const gain = _notifCtx.createGain();
        osc.connect(gain);
        gain.connect(_notifCtx.destination);
        osc.frequency.value = 880;
        osc.type = 'sine';
        gain.gain.setValueAtTime(0.15, _notifCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, _notifCtx.currentTime + 0.2);
        osc.start(_notifCtx.currentTime);
        osc.stop(_notifCtx.currentTime + 0.2);
    } catch (e) {
        // Audio not available - silently ignore
    }
}

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
        } else if (role === 'owner-admin') {
            show = user.is_owner || user.is_admin;
        } else if (role === 'staff') {
            show = user.is_owner || user.is_admin || user.is_manager;
        } else if (role === 'staff-worker') {
            show = user.is_worker || user.is_manager;
        }
        link.hidden = !show;
        link.setAttribute('aria-hidden', show ? 'false' : 'true');
    });
}

function setupBottomNav(user) {
    document.querySelectorAll('#app-bottom-nav .nav-item').forEach((link) => {
        let show = true;
        const navKey = link.dataset.nav;
        if (user.is_superadmin) {
            show = ['dashboard', 'settings'].includes(navKey);
        } else if (navKey === 'production') {
            show = user.is_worker || user.is_manager;
        } else if (navKey === 'clients') {
            show = !user.is_worker;
        }
        link.hidden = !show;
        link.setAttribute('aria-hidden', show ? 'false' : 'true');
    });
}

function escapeText(value) {
    const div = document.createElement('div');
    div.textContent = value ?? '';
    return div.innerHTML;
}

/**
 * Экран «Подписка истекла»: owner может продлить, остальные — обращаются
 * к владельцу. Вызывается при загрузке (is_frozen из /me/) и при 403
 * subscription_expired от любого бизнес-запроса (см. api.js).
 */
async function showFrozenScreen(user) {
    if (document.getElementById('frozen-screen')) return; // уже показан
    try { await window.i18n.init(); } catch (e) { /* i18n уже инициализирован */ }
    if (!user) {
        try {
            user = await window.api.getMe();
            window.currentUser = user;
        } catch (e) {
            return;
        }
    }

    // Прячем «хром» приложения: остаётся только карточка.
    ['app-top-bar', 'app-sidebar', 'app-bottom-nav', 'notifications-btn'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });
    document.body.classList.remove('authenticated');

    const app = document.getElementById('app-content');
    app.innerHTML = `
        <div class="card" id="frozen-screen" style="max-width:420px;margin:6vh auto;text-align:center;padding:28px 24px;">
            <div style="font-size:44px;line-height:1;">🧊</div>
            <h2 style="margin:12px 0 6px;" data-i18n="subscription.frozen_title"></h2>
            <p class="text-sm text-muted" style="margin-bottom:18px;" data-i18n="subscription.frozen_text"></p>
            ${user.is_owner ? `
                <button class="btn btn-primary btn-block" id="frozen-renew" data-i18n="subscription.renew"></button>
                <p class="text-xs text-muted" style="margin-top:10px;" data-i18n="subscription.frozen_hint"></p>` : `
                <p class="text-sm" data-i18n="subscription.contact_owner"></p>`}
            <button class="btn btn-secondary btn-block" id="frozen-logout" style="margin-top:14px;" data-i18n="auth.logout"></button>
        </div>`;
    window.i18n.applyTranslations();

    const renewBtn = document.getElementById('frozen-renew');
    if (renewBtn) renewBtn.addEventListener('click', () => window.subscriptionUI.openModal());
    const logoutBtn = document.getElementById('frozen-logout');
    if (logoutBtn) logoutBtn.addEventListener('click', async () => {
        if (!window.confirmation || await window.confirmation.confirm(
            window.ui.t('auth.logout_confirm'), window.ui.t('auth.logout'))) {
            window.api.logout();
        }
    });
}
window.showFrozenScreen = showFrozenScreen;

/* ────────────────────────────────────────────────────────────────
   Клик в зоне нижней навигации по «выглядывающей» строке контента.

   На низких экранах фиксированная bottom-nav (64px, z-index 30) перекрывает
   низ контента: строка «Хабарлар» в настройках оказывалась частично под ней,
   и клик по видимой части строки попадал в пункт меню «Омбор» — пользователь
   жал «Хабарлар», а открывался склад.

   Если клик пришёлся на зону навигации, но под ней «выглядывает» кликабельная
   строка (≥12px видимой части), активируем строку вместо пункта меню.
   Настоящий клик по пункту меню не трогаем: он ниже строки (y > bottom строки)
   или строка целиком ушла под навигацию (top >= navTop).
   ──────────────────────────────────────────────────────────────── */
document.addEventListener('click', (e) => {
    // Модалка поверх навигации — не перехватываем.
    if (document.querySelector('.modal')) return;
    const nav = document.getElementById('app-bottom-nav');
    if (!nav || getComputedStyle(nav).display === 'none' || !nav.contains(e.target)) return;
    const navTop = nav.getBoundingClientRect().top;
    // Перехватываем ТОЛЬКО клики у верхней кромки навигации (≤12px): там
    // строка ещё визуально соединена со своей видимой частью. Подписи меню и
    // центр иконок сидят ниже — их клики не трогаем, чтобы не перехватывать
    // настоящий тап по пункту навигации (строка под меню при прокрутке есть
    // на любом телефоне).
    if (e.clientY <= navTop || e.clientY - navTop > 12) return;
    // Что «выглядывает» из-под навигации в точке клика по x.
    const peek = document.elementFromPoint(e.clientX, navTop - 2);
    if (!peek || !peek.closest) return;
    const interactive = peek.closest('a[href], .list-row, button, [data-id]');
    if (!interactive) return;
    const r = interactive.getBoundingClientRect();
    // Строка не под навигацией — обычный клик по меню.
    if (r.top >= navTop) return;
    // Строка почти целиком скрыта — клик по ней не намеренный.
    if (r.bottom - navTop < 12) return;
    e.preventDefault();
    e.stopPropagation();
    // Синтетический клик по строке: ссылка сама выполнит переход,
    // а обработчики строки сработают как обычно. Цель клика вне навигации,
    // поэтому capture-обработчик выше вернётся на nav.contains(e.target)
    // и зацикливания не будет.
    interactive.click();
}, true);

async function refreshNotificationBadge() {
    try {
        const response = await window.api.request('/messaging/notifications/?is_read=false');
        const count = response.count ?? (response.results || response).length;
        const badge = document.getElementById('notif-badge');
        if (!badge) return;
        const oldCount = parseInt(badge.textContent) || 0;
        badge.style.display = count > 0 ? 'flex' : 'none';
        badge.textContent = count > 99 ? '99+' : count;
        // Flash эффект если появились новые
        if (count > oldCount) {
            badge.classList.add('notif-flash');
            setTimeout(() => badge.classList.remove('notif-flash'), 1500);
        }
    } catch (e) {
        /* не критично */
    }
}
window.refreshNotificationBadge = refreshNotificationBadge;
