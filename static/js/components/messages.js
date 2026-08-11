/**
 * Корпоративный чат + уведомления.
 *
 * Вкладка «Чат»: двухпанельный интерфейс (список бесед слева, беседа справа),
 * общий чат компании + личные диалоги, поиск сотрудников, непрочитанные,
 * real-time через WebSocket (см. ChatSocket ниже).
 *
 * Вкладка «Уведомления»: системные уведомления (как раньше).
 */

/* ─────────────────────────── WebSocket-клиент ─────────────────────────── */

class ChatSocket {
    constructor() {
        this.ws = null;
        this.handler = null;         // колбэк(message) активной вкладки чата
        this.broadcastHandler = null; // глобальный колбэк (бейдж/тосты/звук)
        this.reconnectDelay = 1000;
        this.pingTimer = null;
        this.shouldRun = false;
    }

    /** Устанавливает обработчик входящих сообщений (или null). */
    setHandler(fn) { this.handler = fn; }

    /** Устанавливает глобальный обработчик, срабатывающий всегда. */
    setBroadcastHandler(fn) { this.broadcastHandler = fn; }

    connect() {
        this.shouldRun = true;
        if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
            return;
        }
        // Access-токен в query-строку WebSocket-URL не передаём (он оседал бы
        // в логах прокси): сначала получаем одноразовый короткоживущий тикет
        // по REST с обычным заголовком Authorization.
        this._fetchTicket();
    }

    async _fetchTicket() {
        const api = window.api;
        if (!api.getTokens().access) return;
        try {
            const data = await api.request('/messaging/ws-ticket/', { method: 'GET' });
            this._open(data.ticket);
        } catch (e) {
            this._scheduleReconnect();
        }
    }

    _open(ticket) {
        const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const url = `${proto}://${window.location.host}/ws/chat/?ticket=${encodeURIComponent(ticket)}`;
        try {
            this.ws = new WebSocket(url);
        } catch (e) {
            this._scheduleReconnect();
            return;
        }

        this.ws.onopen = () => {
            this.reconnectDelay = 1000;
            clearInterval(this.pingTimer);
            this.pingTimer = setInterval(() => this.send({ type: 'ping' }), 25000);
        };
        this.ws.onmessage = (event) => {
            let data;
            try { data = JSON.parse(event.data); } catch (e) { return; }
            if (data.type === 'message') {
                if (this.broadcastHandler) this.broadcastHandler(data.message);
                if (this.handler) this.handler(data.message);
            }
        };
        this.ws.onclose = (event) => {
            clearInterval(this.pingTimer);
            if (!this.shouldRun) return;
            // 4401 — тикет протух или токен истёк: пробуем обновить токен,
            // затем переподключаемся за свежим тикетом.
            if (event.code === 4401) {
                const tokens = window.api.getTokens();
                if (tokens.refresh) window.api.refreshToken(tokens.refresh).finally(() => this._scheduleReconnect());
                else this._scheduleReconnect();
            } else {
                this._scheduleReconnect();
            }
        };
        this.ws.onerror = () => { try { this.ws.close(); } catch (e) { /* ignore */ } };
    }

    _scheduleReconnect() {
        clearInterval(this.pingTimer);
        if (!this.shouldRun) return;
        setTimeout(() => this.connect(), this.reconnectDelay);
        this.reconnectDelay = Math.min(this.reconnectDelay * 2, 15000);
    }

    send(obj) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(obj));
        }
    }
}

window.chatSocket = window.chatSocket || new ChatSocket();


/* ─────────────────────────── Компонент ─────────────────────────── */

class MessagesComponent {
    async render(container) {
        document.getElementById('page-title').setAttribute('data-i18n', 'chat.title');
        this.container = container;
        this.tab = window.router.query.get('tab') === 'notifications' ? 'notifications' : 'chat';

        container.innerHTML = `
            <div class="chat-page">
                <div class="chat-tabs" role="tablist" aria-label="Messages tabs">
                    <button class="chat-tab ${this.tab === 'chat' ? 'active' : ''}" data-tab="chat" id="messages-tab-chat" role="tab" aria-selected="${this.tab === 'chat' ? 'true' : 'false'}" aria-controls="chat-tab-body" data-i18n="chat.tab_chat"></button>
                    <button class="chat-tab ${this.tab === 'notifications' ? 'active' : ''}" data-tab="notifications" id="messages-tab-notifications" role="tab" aria-selected="${this.tab === 'notifications' ? 'true' : 'false'}" aria-controls="chat-tab-body">
                        <span data-i18n="chat.tab_notifications"></span>
                    </button>
                </div>
                <div class="chat-tab-body" id="chat-tab-body" role="tabpanel" aria-labelledby="messages-tab-${this.tab}"></div>
            </div>`;

        container.querySelectorAll('.chat-tab').forEach((btn) => {
            btn.addEventListener('click', () => {
                if (this.tab === btn.dataset.tab) return;
                this.tab = btn.dataset.tab;
                container.querySelectorAll('.chat-tab').forEach((b) => {
                    const active = b === btn;
                    b.classList.toggle('active', active);
                    b.setAttribute('aria-selected', active ? 'true' : 'false');
                });
                const panel = this.bodyEl;
                if (panel) panel.setAttribute('aria-labelledby', `messages-tab-${this.tab}`);
                this.loadTab();
            });
        });

        window.i18n.applyTranslations();
        await this.loadTab();
    }

    get bodyEl() { return this.container.querySelector('#chat-tab-body'); }

    loadTab() {
        if (this.tab === 'notifications') {
            window.chatSocket.setHandler(null);
            return this.loadNotifications();
        }
        return this.loadChat();
    }

    /* ─────────────── Чат ─────────────── */

    async loadChat() {
        this.conversations = [];
        this.activeId = null;
        this.seen = new Set();          // id уже показанных сообщений (антидубли)
        // Сбрасываем инлайновые стили, которые могла выставить вкладка уведомлений.
        this.bodyEl.style.display = '';
        this.bodyEl.style.overflowY = '';
        this.bodyEl.innerHTML = `
            <div class="chat" id="chat-root">
                <div class="chat-aside">
                    <div class="chat-aside-head">
                        <input type="text" class="chat-search" id="chat-search" data-i18n-attr="placeholder" data-i18n="chat.search_placeholder">
                    </div>
                    <div class="chat-list" id="chat-list"></div>
                </div>
                <div class="chat-main" id="chat-main">
                    ${this.emptyMainHtml()}
                </div>
            </div>`;
        this.applyPlaceholders();

        const search = this.bodyEl.querySelector('#chat-search');
        let searchTimer = null;
        search.addEventListener('input', () => {
            clearTimeout(searchTimer);
            const q = search.value.trim();
            searchTimer = setTimeout(() => (q ? this.searchEmployees(q) : this.renderList()), 220);
        });

        // Подключаем WebSocket и вешаем обработчик входящих сообщений.
        window.chatSocket.setHandler((m) => this.onIncoming(m));
        window.chatSocket.connect();

        await this.loadConversations();
    }

    emptyMainHtml() {
        return `
            <div class="chat-empty">
                <div class="chat-empty-icon">💬</div>
                <div style="font-weight:600;" data-i18n="chat.select_chat"></div>
                <div class="text-sm" data-i18n="chat.select_chat_hint"></div>
            </div>`;
    }

    async loadConversations() {
        const listEl = this.bodyEl.querySelector('#chat-list');
        listEl.innerHTML = `<div class="list-state list-state-loading" style="padding:24px;"><span class="spinner"></span></div>`;
        try {
            const resp = await window.api.request('/messaging/conversations/');
            this.conversations = (resp.results || resp).slice();
            this.sortConversations();
            this.renderList();
        } catch (e) {
            listEl.innerHTML = `<div class="chat-empty"><span data-i18n="chat.error"></span></div>`;
            window.i18n.applyTranslations();
        }
    }

    sortConversations() {
        this.conversations.sort((a, b) => {
            if (a.kind === 'general' && b.kind !== 'general') return -1;
            if (b.kind === 'general' && a.kind !== 'general') return 1;
            return new Date(b.updated_at) - new Date(a.updated_at);
        });
    }

    renderList() {
        const listEl = this.bodyEl.querySelector('#chat-list');
        if (!this.conversations.length) {
            listEl.innerHTML = `<div class="chat-empty" style="min-height:120px;"><span data-i18n="chat.no_conversations"></span></div>`;
            window.i18n.applyTranslations();
            return;
        }
        listEl.innerHTML = this.conversations.map((c) => this.conversationItemHtml(c)).join('');
        listEl.querySelectorAll('[data-conv]').forEach((el) => {
            el.addEventListener('click', () => this.openConversation(Number(el.dataset.conv)));
        });
        window.i18n.applyTranslations();
    }

    conversationItemHtml(c) {
        const isGeneral = c.kind === 'general';
        const name = isGeneral ? window.ui.t('chat.general') : (c.display_title || '—');
        const avatarClass = isGeneral ? 'chat-avatar general' : 'chat-avatar';
        const avatarStyle = isGeneral ? '' : `style="background:${this.avatarColor(name)}"`;
        const avatarText = isGeneral ? '#' : this.initials(name);
        const last = c.last_message;
        const lastText = last
            ? `${last.sender_name ? window.ui.escape(last.sender_name.split(' ')[0]) + ': ' : ''}${window.ui.escape(last.content)}`
            : `<span data-i18n="chat.no_messages"></span>`;
        const time = last ? this.shortTime(last.created_at) : '';
        const unread = c.unread_count > 0
            ? `<span class="chat-unread">${c.unread_count > 99 ? '99+' : c.unread_count}</span>` : '';
        return `
            <button class="chat-item ${c.id === this.activeId ? 'active' : ''}" data-conv="${c.id}">
                <div class="${avatarClass}" ${avatarStyle}>${avatarText}</div>
                <div class="chat-item-body">
                    <div class="chat-item-top">
                        <span class="chat-item-name">${window.ui.escape(name)}</span>
                        <span class="chat-item-time">${time}</span>
                    </div>
                    <div class="chat-item-bottom">
                        <span class="chat-item-last">${lastText}</span>
                        ${unread}
                    </div>
                </div>
            </button>`;
    }

    async searchEmployees(query) {
        const listEl = this.bodyEl.querySelector('#chat-list');
        try {
            const resp = await window.api.request(`/messaging/employees/?search=${encodeURIComponent(query)}`);
            const employees = resp.results || resp;
            if (!employees.length) {
                listEl.innerHTML = `<div class="chat-empty" style="min-height:120px;"><span data-i18n="chat.no_employees"></span></div>`;
                window.i18n.applyTranslations();
                return;
            }
            listEl.innerHTML = `<div class="chat-section-label" data-i18n="chat.employees"></div>` + employees.map((u) => {
                const name = u.full_name || u.username;
                return `
                    <button class="chat-item" data-user="${u.id}">
                        <div class="chat-avatar" style="background:${this.avatarColor(name)}">${this.initials(name)}</div>
                        <div class="chat-item-body">
                            <div class="chat-item-top"><span class="chat-item-name">${window.ui.escape(name)}</span></div>
                            <div class="chat-item-bottom"><span class="chat-item-last">${window.ui.escape(u.display_role || u.role)}</span></div>
                        </div>
                    </button>`;
            }).join('');
            listEl.querySelectorAll('[data-user]').forEach((el) => {
                el.addEventListener('click', () => this.startDirect(Number(el.dataset.user)));
            });
            window.i18n.applyTranslations();
        } catch (e) {
            window.toast.error(window.ui.errorText ? window.ui.errorText(e) : window.ui.t('chat.error'));
        }
    }

    async startDirect(userId) {
        try {
            const conv = await window.api.request('/messaging/conversations/start_direct/', {
                method: 'POST', body: JSON.stringify({ user_id: userId }),
            });
            const existing = this.conversations.find((c) => c.id === conv.id);
            if (!existing) this.conversations.push(conv);
            this.sortConversations();
            const search = this.bodyEl.querySelector('#chat-search');
            if (search) search.value = '';
            this.renderList();
            this.openConversation(conv.id);
        } catch (e) {
            window.toast.error(window.ui.errorText ? window.ui.errorText(e) : window.ui.t('chat.error'));
        }
    }

    async openConversation(id) {
        this.activeId = id;
        const conv = this.conversations.find((c) => c.id === id);
        this.renderList();

        const mainEl = this.bodyEl.querySelector('#chat-main');
        const title = conv ? (conv.kind === 'general' ? window.ui.t('chat.general') : conv.display_title) : '';
        const sub = conv && conv.kind === 'general' ? window.ui.t('chat.general_desc')
            : (conv && conv.other_user ? (window.i18n.translate('roles.' + conv.other_user.role)) : '');
        mainEl.innerHTML = `
            <div class="chat-main-head">
                <button class="chat-back" id="chat-back" aria-label="Back">‹</button>
                <div class="${conv && conv.kind === 'general' ? 'chat-avatar general' : 'chat-avatar'}"
                     ${conv && conv.kind === 'general' ? '' : `style="background:${this.avatarColor(title || '')}"`}>
                    ${conv && conv.kind === 'general' ? '#' : this.initials(title || '?')}
                </div>
                <div style="min-width:0;">
                    <div class="chat-main-title">${window.ui.escape(title || '')}</div>
                    <div class="chat-main-sub">${window.ui.escape(sub || '')}</div>
                </div>
            </div>
            <div class="chat-messages" id="chat-messages"></div>
            <div class="chat-input">
                <textarea id="chat-textarea" rows="1" data-i18n-attr="placeholder" data-i18n="chat.type_message"></textarea>
                <button class="chat-send" id="chat-send" aria-label="Send">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
                </button>
            </div>`;
        this.applyPlaceholders();

        // Мобильный режим: показать панель беседы.
        const root = this.bodyEl.querySelector('#chat-root');
        root.classList.add('chat--open');
        mainEl.querySelector('#chat-back').addEventListener('click', () => {
            root.classList.remove('chat--open');
            this.activeId = null;
            this.renderList();
        });

        // Ввод: Enter — отправить, Shift+Enter — перенос строки. Автовысота.
        const textarea = mainEl.querySelector('#chat-textarea');
        const autoGrow = () => { textarea.style.height = 'auto'; textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px'; };
        textarea.addEventListener('input', autoGrow);
        textarea.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this.sendMessage(); }
        });
        mainEl.querySelector('#chat-send').addEventListener('click', () => this.sendMessage());

        await this.loadMessages(id);
        textarea.focus();
    }

    async loadMessages(id) {
        const box = this.bodyEl.querySelector('#chat-messages');
        box.innerHTML = `<div class="list-state list-state-loading" style="margin:auto;"><span class="spinner"></span></div>`;
        try {
            const messages = await window.api.request(`/messaging/conversations/${id}/messages/`);
            this.seen = new Set(messages.map((m) => m.id));
            if (!messages.length) {
                box.innerHTML = `<div class="chat-empty" style="margin:auto;"><span data-i18n="chat.no_messages"></span></div>`;
                window.i18n.applyTranslations();
            } else {
                box.innerHTML = messages.map((m) => this.messageHtml(m)).join('');
                this.scrollToBottom();
            }
            // Отмечаем прочитанным + обнуляем счётчик в списке.
            this.markRead(id);
        } catch (e) {
            box.innerHTML = `<div class="chat-empty" style="margin:auto;"><span data-i18n="chat.error"></span></div>`;
            window.i18n.applyTranslations();
        }
    }

    isMine(m) {
        // Надёжно определяем «своё» по id отправителя: WebSocket-пейлоад не
        // содержит is_mine, а из-за гонки эхо может прийти раньше ответа POST.
        if (typeof m.is_mine === 'boolean') return m.is_mine;
        return !!(window.currentUser && m.sender === window.currentUser.id);
    }

    messageHtml(m) {
        const mine = this.isMine(m);
        const conv = this.conversations.find((c) => c.id === this.activeId);
        const showSender = !mine && conv && conv.kind === 'general';
        return `
            <div class="msg ${mine ? 'mine' : 'theirs'}" data-msg="${m.id}">
                ${showSender ? `<div class="msg-sender">${window.ui.escape(m.sender_name)}</div>` : ''}
                <span>${window.ui.escape(m.content)}</span><span class="msg-time">${this.shortTime(m.created_at)}</span>
            </div>`;
    }

    async sendMessage() {
        const textarea = this.bodyEl.querySelector('#chat-textarea');
        const content = textarea.value.trim();
        if (!content || !this.activeId) return;
        textarea.value = '';
        textarea.style.height = 'auto';
        try {
            const msg = await window.api.request('/messaging/messages/', {
                method: 'POST', body: JSON.stringify({ conversation: this.activeId, content }),
            });
            this.appendMessage(msg);
            this.bumpConversation(this.activeId, msg, true);
        } catch (e) {
            window.toast.error(window.ui.errorText ? window.ui.errorText(e) : window.ui.t('chat.error'));
            textarea.value = content; // возвращаем текст при ошибке
        }
    }

    appendMessage(m) {
        if (this.seen.has(m.id)) return;
        this.seen.add(m.id);
        const box = this.bodyEl.querySelector('#chat-messages');
        if (!box) return;
        const empty = box.querySelector('.chat-empty');
        if (empty) box.innerHTML = '';
        box.insertAdjacentHTML('beforeend', this.messageHtml(m));
        this.scrollToBottom();
    }

    /** Входящее по WebSocket. */
    onIncoming(m) {
        if (m.conversation === this.activeId) {
            this.appendMessage(m);
            this.markRead(this.activeId);
            this.bumpConversation(m.conversation, m, true);
        } else {
            const known = this.conversations.find((c) => c.id === m.conversation);
            if (known) {
                this.bumpConversation(m.conversation, m, false);
            } else {
                // Новый диалог (кто-то написал первым) — перечитываем список.
                this.loadConversations();
            }
        }
    }

    bumpConversation(id, m, read) {
        const conv = this.conversations.find((c) => c.id === id);
        if (!conv) return;
        conv.last_message = { content: m.content, created_at: m.created_at, sender: m.sender, sender_name: m.sender_name };
        conv.updated_at = m.created_at;
        if (!read && !this.isMine(m)) conv.unread_count = (conv.unread_count || 0) + 1;
        if (read) conv.unread_count = 0;
        this.sortConversations();
        this.renderList();
    }

    async markRead(id) {
        const conv = this.conversations.find((c) => c.id === id);
        if (conv) conv.unread_count = 0;
        this.renderList();
        try { await window.api.request(`/messaging/conversations/${id}/read/`, { method: 'POST' }); } catch (e) { /* некритично */ }
        if (window.refreshNotificationBadge) window.refreshNotificationBadge();
    }

    scrollToBottom() {
        const box = this.bodyEl.querySelector('#chat-messages');
        if (box) box.scrollTop = box.scrollHeight;
    }

    /* ─────────────── Утилиты ─────────────── */

    applyPlaceholders() {
        // Переводим data-i18n для placeholder-атрибутов.
        this.bodyEl.querySelectorAll('[data-i18n-attr="placeholder"]').forEach((el) => {
            const key = el.getAttribute('data-i18n');
            if (key) el.setAttribute('placeholder', window.ui.t(key));
        });
        window.i18n.applyTranslations();
    }

    initials(name) {
        const parts = String(name || '?').trim().split(/\s+/);
        const text = ((parts[0] || '?')[0] + (parts[1] ? parts[1][0] : '')).toUpperCase();
        return window.ui.escape(text);
    }

    avatarColor(seed) {
        const colors = ['#e5484d', '#f76808', '#ffb224', '#30a46c', '#0091ff', '#8e4ec6', '#e93d82', '#12a594'];
        let h = 0;
        for (let i = 0; i < String(seed).length; i++) h = (h * 31 + seed.charCodeAt(i)) & 0xffffffff;
        return colors[Math.abs(h) % colors.length];
    }

    shortTime(iso) {
        if (!iso) return '';
        return new Date(iso).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
    }

    /* ─────────────── Уведомления (как прежде) ─────────────── */

    groupByDay(notifications) {
        const today = new Date(); today.setHours(0, 0, 0, 0);
        const yesterday = new Date(today); yesterday.setDate(yesterday.getDate() - 1);
        const groups = [];
        const byKey = {};
        notifications.forEach((n) => {
            const d = new Date(n.created_at); d.setHours(0, 0, 0, 0);
            let label;
            if (d.getTime() === today.getTime()) label = window.ui.t('common.today');
            else if (d.getTime() === yesterday.getTime()) label = window.ui.t('periods.yesterday');
            else label = window.ui.date(n.created_at);
            if (!byKey[label]) { byKey[label] = { label, items: [] }; groups.push(byKey[label]); }
            byKey[label].items.push(n);
        });
        return groups;
    }

    notificationStyle(type) {
        const map = {
            new_order: ['🆕', 'blue'], new_expense: ['🧾', 'orange'],
            unpaid_client: ['⚠️', 'red'], overdue_debt: ['⏰', 'red'],
            worker_refused: ['✕', 'red'], work_awaiting: ['📋', 'orange'],
            cash_change: ['💰', 'green'], report_ready: ['📊', 'blue'],
            task_assigned: ['🛠️', 'blue'], task_changed: ['✏️', 'purple'],
            task_cancelled: ['🚫', 'red'], work_confirmed: ['✅', 'green'],
            work_rejected: ['✕', 'red'], new_message: ['✉️', 'blue'],
            work_accrued: ['💵', 'green'], material_shortage: ['⚠️', 'orange'],
        };
        return map[type] || ['🔔', 'blue'];
    }

    /**
     * Куда ведёт уведомление. Возвращает '' — если вести некуда:
     * тогда строка остаётся некликабельной, а не бросает в раздел без прав.
     *
     * Права важны: работнику закрыты финансы (finance.js рендерит заглушку
     * для не-владельца) и клиенты (пункт меню у него скрыт).
     */
    notificationRoute(n) {
        const user = window.currentUser || {};
        const owner = !!user.is_owner;
        const staff = owner || !!user.is_admin || !!user.is_manager;
        const clientUnpaid = n.related_client
            ? `#/orders?client=${n.related_client}&payment_status=unpaid` : (staff ? '#/clients' : '');
        const map = {
            new_order: '#/orders',
            new_expense: owner ? '#/finance' : '',
            cash_change: owner ? '#/finance' : '',
            report_ready: owner ? '#/finance' : '',
            // Неоплата и просрочка ведут на неоплаченные заказы этого клиента,
            // а не на общий список клиентов: иначе долг приходится выискивать.
            unpaid_client: clientUnpaid,
            overdue_debt: clientUnpaid,
            material_shortage: '#/warehouse',
            worker_refused: '#/production',
            work_awaiting: '#/production',
            task_assigned: '#/production',
            task_changed: '#/production',
            task_cancelled: '#/production',
            work_confirmed: '#/production',
            work_rejected: '#/production',
            work_accrued: '#/production',
            new_message: '#/messages',
        };
        return map[n.type] || '';
    }

    /** Клик по уведомлению: пометить прочитанным и перейти в нужный раздел. */
    async openNotification(id) {
        const n = (this.notifications || []).find((item) => String(item.id) === String(id));
        if (!n) return;
        const route = this.notificationRoute(n);
        if (!n.is_read) {
            n.is_read = true;
            try {
                await window.api.request(`/messaging/notifications/${n.id}/mark_read/`, { method: 'POST' });
                if (window.refreshNotificationBadge) window.refreshNotificationBadge();
            } catch (e) { /* переход важнее отметки */ }
        }
        if (route) window.location.hash = route.slice(1);
        else this.loadNotifications();
    }

    renderNotification(n) {
        const [icon, color] = this.notificationStyle(n.type);
        const route = this.notificationRoute(n);
        const clickable = route ? `cursor:pointer;` : 'cursor:default;';
        return `
            <div class="list-row" ${route ? `data-notif-id="${n.id}" role="button" tabindex="0"` : ''}
                 style="${clickable}${n.is_read ? '' : 'background:var(--primary-soft);'}">
                <div style="display:flex;align-items:center;gap:12px;min-width:0;">
                    <div class="stat-icon ${color}" style="width:36px;height:36px;font-size:16px;border-radius:10px;">${icon}</div>
                    <div style="min-width:0;">
                        <div style="font-weight:600;font-size:14px;" data-i18n="notifications.${n.type}"></div>
                        <div class="text-sm text-muted" style="overflow:hidden;text-overflow:ellipsis;">${window.ui.escape(n.message)}</div>
                    </div>
                </div>
                <div style="display:flex;align-items:center;gap:8px;flex-shrink:0;">
                    <span class="text-sm text-muted">${window.ui.datetime(n.created_at)}</span>
                    ${n.is_read ? '' : '<span style="width:8px;height:8px;border-radius:50%;background:var(--primary);display:inline-block;"></span>'}
                </div>
            </div>`;
    }

    async loadNotifications() {
        const el = this.bodyEl;
        el.style.display = 'block';
        el.style.overflowY = 'auto';
        // Пользователь мог уйти со страницы, пока шёл запрос: контейнера
        // больше нет, рисовать некуда.
        if (window.listStates.gone(el)) return;
        window.listStates.loading(el, window.ui.t('common.loading'));
        try {
            const response = await window.api.request('/messaging/notifications/');
            const notifications = response.results || response;
            this.notifications = notifications;
            if (!notifications.length) {
                window.listStates.empty(el, window.ui.t('messages_section.no_notifications'));
                return;
            }
            const unread = notifications.filter((n) => !n.is_read).length;
            const groups = this.groupByDay(notifications);
            el.innerHTML = `
                ${unread ? `<button class="btn btn-secondary btn-sm btn-block" id="mark-all-read" style="margin-bottom:12px;" data-i18n="messages_section.mark_all_read"></button>` : ''}
                ${groups.map((g) => `
                    <div class="section-title">${window.ui.escape(g.label)}</div>
                    <div class="list-group">
                        ${g.items.map((n) => this.renderNotification(n)).join('')}
                    </div>`).join('')}`;
            el.querySelectorAll('[data-notif-id]').forEach((row) => {
                const open = () => this.openNotification(row.dataset.notifId);
                row.addEventListener('click', open);
                row.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
                });
            });
            const markAll = el.querySelector('#mark-all-read');
            if (markAll) {
                markAll.addEventListener('click', async () => {
                    await window.api.request('/messaging/notifications/mark_all_read/', { method: 'POST' });
                    window.refreshNotificationBadge();
                    this.loadNotifications();
                });
            }
            window.i18n.applyTranslations();
        } catch (e) {
            window.listStates.error(el, window.ui.t('common.error'), () => this.loadNotifications());
        }
    }
}

window.MessagesComponent = new MessagesComponent();
