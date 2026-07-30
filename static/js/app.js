/**
 * App bootstrap: авторизация, роль, навигация (сайдбар для десктопа,
 * нижнее меню для мобильных), маршруты SPA, WebSocket уведомления.
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
        // Скрываем пункты нижней навигации, недоступные для superadmin
        // (сайдбар фильтруется в setupSidebar через data-role).
        ['nav-orders', 'nav-warehouse', 'nav-clients', 'nav-production'].forEach(function(id) {
            let el = document.getElementById(id);
            if (el) el.style.display = 'none';
        });
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
    window.router.addRoute('/orders/kanban', window.KanbanComponent);
    window.router.addRoute('/production', window.ProductionComponent);
    window.router.addRoute('/finance', window.FinanceComponent);
    window.router.addRoute('/messages', window.MessagesComponent);
    window.router.addRoute('/settings', window.SettingsComponent);
    window.router.addRoute('/audit', window.AuditComponent);
    window.router.addRoute('/backup', window.SettingsComponent);

    window.router.handleRoute();

    // Загрузка тёмной темы
    if (localStorage.getItem('theme') === 'dark') {
        document.body.classList.add('theme-dark');
    }

    // Регистрация Service Worker
    registerServiceWorker();

    // Запускаем WebSocket для уведомлений в реальном времени
    connectWebSocket();
    refreshNotificationBadge();
    setInterval(refreshNotificationBadge, 60000);
});

/**
 * WebSocket-соединение для real-time уведомлений.
 * Переподключается при разрыве с exponential backoff.
 */
let ws = null;
let wsReconnectTimer = null;
let wsReconnectAttempts = 0;

function connectWebSocket() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    const tokens = window.api.getTokens();
    const token = tokens.access;
    if (!token) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${window.location.host}/ws/chat/?token=${token}`;

    try {
        ws = new WebSocket(url);
    } catch (e) {
        scheduleReconnect();
        return;
    }

    ws.onopen = () => {
        wsReconnectAttempts = 0;
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.type === 'message') {
                // Новое сообщение — обновляем бейдж
                refreshNotificationBadge();
                // Воспроизводим звук уведомления
                playNotificationSound();
                // Фоновое уведомление через Service Worker
                sendSWNotification({
                    title: `✉️ ${data.message?.sender_name || 'Сообщение'}`,
                    body: (data.message?.content || '').slice(0, 120),
                    tag: 'chat_message',
                    data: { url: '#/messages' },
                });
                // Показываем тост
                const msg = data.message || {};
                if (msg.sender_name) {
                    window.toast.info(`✉️ ${msg.sender_name}: ${(msg.content || '').slice(0, 60)}`);
                }
            } else if (data.type === 'notification') {
                // Системное уведомление (новая задача, подтверждение и т.д.)
                refreshNotificationBadge();
                playNotificationSound();
                sendSWNotification({
                    title: `🔔 ${data.title || 'Уведомление'}`,
                    body: data.body || '',
                    tag: 'system_notification',
                    data: { url: data.url || '#/messages?tab=notifications' },
                });
                if (data.title) {
                    window.toast.info(`🔔 ${data.title}`);
                }
            }
        } catch (e) {
            // ignore parse errors
        }
    };

    ws.onclose = () => {
        ws = null;
        scheduleReconnect();
    };

    ws.onerror = () => {
        // onclose будет вызван следом
    };
}

function scheduleReconnect() {
    if (wsReconnectTimer) return;
    const delay = Math.min(1000 * Math.pow(2, wsReconnectAttempts), 30000);
    wsReconnectAttempts++;
    wsReconnectTimer = setTimeout(() => {
        wsReconnectTimer = null;
        connectWebSocket();
    }, delay);
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
            body: 'Уведомления включены! 🎉',
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
