/**
 * Сообщения и уведомления: входящие, отправленные, уведомления.
 * Получатели ограничены правами роли (эндпоинт /messages/recipients/).
 */
class MessagesComponent {
    async render(container) {
        document.getElementById('page-title').setAttribute('data-i18n', 'messages_section.title');
        this.container = container;
        this.tab = window.router.query.get('tab') === 'notifications' ? 'notifications' : 'inbox';

        container.innerHTML = `
            <div class="tabs">
                <button class="tab-btn ${this.tab === 'inbox' ? 'active' : ''}" data-tab="inbox" data-i18n="messages_section.inbox"></button>
                <button class="tab-btn ${this.tab === 'sent' ? 'active' : ''}" data-tab="sent" data-i18n="messages_section.sent"></button>
                <button class="tab-btn ${this.tab === 'notifications' ? 'active' : ''}" data-tab="notifications" data-i18n="messages_section.notifications"></button>
            </div>
            <button class="btn btn-primary btn-block" id="compose-btn" style="margin-bottom:12px;" data-i18n="messages_section.new_message"></button>
            <div id="messages-content"></div>
        `;

        container.querySelectorAll('.tab-btn').forEach((btn) => {
            btn.addEventListener('click', () => {
                container.querySelectorAll('.tab-btn').forEach((b) => b.classList.remove('active'));
                btn.classList.add('active');
                this.tab = btn.dataset.tab;
                this.loadTab();
            });
        });
        container.querySelector('#compose-btn').addEventListener('click', () => this.openCompose());

        window.i18n.applyTranslations();
        await this.loadTab();
    }

    loadTab() {
        if (this.tab === 'notifications') return this.loadNotifications();
        return this.loadMessages(this.tab);
    }

    get contentEl() {
        return this.container.querySelector('#messages-content');
    }

    async loadMessages(box) {
        const el = this.contentEl;
        window.listStates.loading(el, window.ui.t('common.loading'));
        try {
            const response = await window.api.request(`/messaging/messages/?box=${box}`);
            const messages = response.results || response;
            if (!messages.length) {
                window.listStates.empty(el, window.ui.t('messages_section.no_messages'));
                return;
            }
            el.innerHTML = `
                <div class="list-group">
                    ${messages.map((m) => `
                        <div class="list-row" data-id="${m.id}" style="${box === 'inbox' && !m.is_read ? 'background:#eef4ff;' : ''}">
                            <div style="min-width:0;">
                                <div style="font-weight:600;font-size:14px;">
                                    ${box === 'sent'
                                        ? (m.is_group ? `<span data-i18n="messages_section.to_all"></span>` : window.ui.escape(m.recipient_name || ''))
                                        : window.ui.escape(m.sender_name)}
                                </div>
                                <div class="text-sm text-muted" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                                    ${window.ui.escape(m.subject || m.content.slice(0, 60))}
                                </div>
                            </div>
                            <span class="text-sm text-muted" style="flex-shrink:0;">${window.ui.datetime(m.created_at)}</span>
                        </div>`).join('')}
                </div>`;
            el.querySelectorAll('[data-id]').forEach((row) => {
                row.addEventListener('click', () => {
                    const message = messages.find((m) => m.id === Number(row.dataset.id));
                    this.openMessage(message, box);
                });
            });
            window.i18n.applyTranslations();
        } catch (e) {
            window.listStates.error(el, window.ui.t('common.error'), () => this.loadMessages(box));
        }
    }

    async openMessage(m, box) {
        const modal = window.ui.modal('messages_section.title', `
            <div class="list-group" style="box-shadow:none;border:1px solid #efeff4;margin-bottom:12px;">
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm text-muted" data-i18n="messages_section.from"></span>
                    <span class="text-sm font-bold">${window.ui.escape(m.sender_name)}</span>
                </div>
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm text-muted" data-i18n="messages_section.to"></span>
                    <span class="text-sm font-bold">${m.is_group ? window.ui.t('messages_section.to_all') : window.ui.escape(m.recipient_name || '')}</span>
                </div>
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm text-muted" data-i18n="common.date"></span>
                    <span class="text-sm font-bold">${window.ui.datetime(m.created_at)}</span>
                </div>
            </div>
            ${m.subject ? `<p style="font-weight:600;margin-bottom:8px;">${window.ui.escape(m.subject)}</p>` : ''}
            <p style="white-space:pre-wrap;">${window.ui.escape(m.content)}</p>
        `);
        void modal;

        if (box === 'inbox' && !m.is_read && !m.is_group) {
            try {
                await window.api.request(`/messaging/messages/${m.id}/mark_read/`, { method: 'POST' });
                this.loadMessages('inbox');
            } catch (e) { /* некритично */ }
        }
    }

    /** Группирует уведомления по дню: Сегодня / Вчера / дата. */
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

    /** Иконка и цвет по типу уведомления. */
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

    renderNotification(n) {
        const [icon, color] = this.notificationStyle(n.type);
        return `
            <div class="list-row" style="cursor:default;${n.is_read ? '' : 'background:var(--primary-soft);'}">
                <div style="display:flex;align-items:center;gap:12px;min-width:0;">
                    <div class="stat-icon ${color}" style="width:36px;height:36px;font-size:16px;border-radius:10px;">${icon}</div>
                    <div style="min-width:0;">
                        <div style="font-weight:600;font-size:14px;" data-i18n="notifications.${n.type}"></div>
                        <div class="text-sm text-muted" style="overflow:hidden;text-overflow:ellipsis;">${window.ui.escape(n.message)}</div>
                    </div>
                </div>
                <div style="display:flex;align-items:center;gap:8px;flex-shrink:0;">
                    <span class="text-sm text-muted">${window.ui.datetime(n.created_at)}</span>
                    ${n.is_read ? '' : '<span style="width:8px;height:8px;border-radius:50%;background:var(--primary-color);display:inline-block;"></span>'}
                </div>
            </div>`;
    }

    async loadNotifications() {
        const el = this.contentEl;
        window.listStates.loading(el, window.ui.t('common.loading'));
        try {
            const response = await window.api.request('/messaging/notifications/');
            const notifications = response.results || response;
            if (!notifications.length) {
                window.listStates.empty(el, window.ui.t('messages_section.no_notifications'));
                return;
            }
            const unread = notifications.filter((n) => !n.is_read).length;
            // Группировка по дням: Сегодня / Вчера / дата.
            const groups = this.groupByDay(notifications);
            el.innerHTML = `
                ${unread ? `<button class="btn btn-secondary btn-sm btn-block" id="mark-all-read" style="margin-bottom:12px;" data-i18n="messages_section.mark_all_read"></button>` : ''}
                ${groups.map((g) => `
                    <div class="section-title">${window.ui.escape(g.label)}</div>
                    <div class="list-group">
                        ${g.items.map((n) => this.renderNotification(n)).join('')}
                    </div>`).join('')}`;
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

    async openCompose() {
        let recipients = [];
        try {
            recipients = await window.api.request('/messaging/messages/recipients/');
        } catch (e) { /* пустой список - ниже покажем только группу */ }
        const isOwner = window.currentUser.is_owner;

        const modal = window.ui.modal('messages_section.new_message', `
            <form id="compose-form">
                <div class="form-group"><label data-i18n="messages_section.to"></label>
                    <select name="recipient" class="form-control" required>
                        ${isOwner ? `<option value="__all__" data-i18n="messages_section.to_all"></option>` : ''}
                        ${recipients.map((u) => `
                            <option value="${u.id}">${window.ui.escape(u.full_name || u.username)} (${window.ui.t('roles.' + u.role)})</option>`).join('')}
                    </select></div>
                <div class="form-group"><label data-i18n="messages_section.subject"></label>
                    <input name="subject" class="form-control"></div>
                <div class="form-group"><label data-i18n="messages_section.content"></label>
                    <textarea name="content" class="form-control" rows="4" required data-i18n="messages_section.type_message"></textarea></div>
                <button type="submit" class="btn btn-primary btn-block" data-i18n="messages_section.send"></button>
            </form>
        `);

        modal.querySelector('#compose-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target));
            if (data.recipient === '__all__') {
                data.is_group = true;
                delete data.recipient;
            }
            await window.ui.submitGuard(e.target.querySelector('button[type=submit]'), async () => {
                try {
                    await window.api.request('/messaging/messages/', { method: 'POST', body: JSON.stringify(data) });
                    modal.remove();
                    window.toast.success(window.ui.t('common.success'));
                    this.tab = 'sent';
                    this.container.querySelectorAll('.tab-btn').forEach((b) => b.classList.toggle('active', b.dataset.tab === 'sent'));
                    await this.loadMessages('sent');
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        });
    }
}

window.MessagesComponent = new MessagesComponent();
