/**
 * Компонент для управления сообщениями и уведомлениями.
 *
 * Отображает список сообщений и уведомлений, позволяет отправлять сообщения
 * и отмечать уведомления как прочитанные.
 */
class MessagesComponent {
    /**
     * Рендерит страницу сообщений.
     *
     * @param {HTMLElement} container - Контейнер для рендеринга
     */
    async render(container) {
        container.innerHTML = `
            <header style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                <h1 data-i18n="messages.title">Хабарлар</h1>
                <div style="display: flex; gap: 10px;">
                    <select id="messages-tab" class="form-control" style="width: auto;">
                        <option value="inbox" data-i18n="messages.inbox">Келган хабарлар</option>
                        <option value="sent" data-i18n="messages.sent">Юборилган</option>
                        <option value="notifications" data-i18n="messages.notifications">Уведомления</option>
                    </select>
                </div>
            </header>
            
            <div id="messages-content">
                <!-- Содержимое загружается динамически -->
            </div>
        `;

        await this.loadInbox(container);
        this.setupEventListeners(container);
    }

    /**
     * Загружает входящие сообщения.
     *
     * @param {HTMLElement} container - Контейнер
     */
    async loadInbox(container) {
        const contentEl = container.querySelector('#messages-content');
        
        try {
            const data = await window.api.request('/messaging/messages/?is_read=false');
            
            if (data && data.length > 0) {
                contentEl.innerHTML = `
                    <div style="display: flex; justify-content: flex-end; margin-bottom: 15px;">
                        <button id="compose-btn" class="btn btn-primary" data-i18n="messages.compose">Хабар юбориш</button>
                    </div>
                    <div class="card" style="overflow-x: auto;">
                        <table style="width: 100%; border-collapse: collapse; text-align: left;">
                            <thead>
                                <tr style="border-bottom: 2px solid #eee;">
                                    <th style="padding: 10px;" data-i18n="messages.from">Кимдан</th>
                                    <th style="padding: 10px;" data-i18n="messages.subject">Мавзу</th>
                                    <th style="padding: 10px;" data-i18n="messages.date">Сана</th>
                                    <th style="padding: 10px;" data-i18n="common.actions">Амаллар</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${data.map(m => `
                                    <tr style="border-bottom: 1px solid #eee; ${m.is_unread ? 'font-weight: bold;' : ''}">
                                        <td style="padding: 10px;">${m.sender_name}</td>
                                        <td style="padding: 10px;">${m.subject || '(без темы)'}</td>
                                        <td style="padding: 10px;">${new Date(m.created_at).toLocaleString()}</td>
                                        <td style="padding: 10px;">
                                            <button class="btn btn-sm btn-info" onclick="window.messages.viewMessage(${m.id})">
                                                <span data-i18n="common.view">Кўриш</span>
                                            </button>
                                            ${m.is_unread ? `
                                                <button class="btn btn-sm btn-success" onclick="window.messages.markRead(${m.id})">
                                                    <span data-i18n="messages.mark_read">Ўқиш</span>
                                                </button>
                                            ` : ''}
                                        </td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                `;
            } else {
                contentEl.innerHTML = `
                    <div style="display: flex; justify-content: flex-end; margin-bottom: 15px;">
                        <button id="compose-btn" class="btn btn-primary" data-i18n="messages.compose">Хабар юбориш</button>
                    </div>
                    <div class="card" style="padding: 20px; text-align: center;" data-i18n="messages.no_messages">Хабарлар йўқ</div>
                `;
            }
            window.i18n.applyTranslations();
            
            const composeBtn = contentEl.querySelector('#compose-btn');
            if (composeBtn) {
                composeBtn.addEventListener('click', () => this.showComposeModal(container));
            }
        } catch (e) {
            console.error('Failed to load messages', e);
            contentEl.innerHTML = `<div class="card" style="padding: 20px; text-align: center; color: red;" data-i18n="common.error">Хатолик</div>`;
            window.i18n.applyTranslations();
        }
    }

    /**
     * Загружает отправленные сообщения.
     *
     * @param {HTMLElement} container - Контейнер
     */
    async loadSent(container) {
        const contentEl = container.querySelector('#messages-content');
        
        try {
            const data = await window.api.request('/messaging/messages/');
            // Фильтруем только отправленные сообщения
            const sentMessages = data.filter(m => m.sender_name === window.api.getMe().username);
            
            if (sentMessages.length > 0) {
                contentEl.innerHTML = `
                    <div class="card" style="overflow-x: auto;">
                        <table style="width: 100%; border-collapse: collapse; text-align: left;">
                            <thead>
                                <tr style="border-bottom: 2px solid #eee;">
                                    <th style="padding: 10px;" data-i18n="messages.to">Кимга</th>
                                    <th style="padding: 10px;" data-i18n="messages.subject">Мавзу</th>
                                    <th style="padding: 10px;" data-i18n="messages.date">Сана</th>
                                    <th style="padding: 10px;" data-i18n="common.actions">Амаллар</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${sentMessages.map(m => `
                                    <tr style="border-bottom: 1px solid #eee;">
                                        <td style="padding: 10px;">${m.recipient_name || 'Группа'}</td>
                                        <td style="padding: 10px;">${m.subject || '(без темы)'}</td>
                                        <td style="padding: 10px;">${new Date(m.created_at).toLocaleString()}</td>
                                        <td style="padding: 10px;">
                                            <button class="btn btn-sm btn-info" onclick="window.messages.viewMessage(${m.id})">
                                                <span data-i18n="common.view">Кўриш</span>
                                            </button>
                                        </td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                `;
            } else {
                contentEl.innerHTML = `<div class="card" style="padding: 20px; text-align: center;" data-i18n="messages.no_messages">Хабарлар йўқ</div>`;
            }
            window.i18n.applyTranslations();
        } catch (e) {
            console.error('Failed to load sent messages', e);
            contentEl.innerHTML = `<div class="card" style="padding: 20px; text-align: center; color: red;" data-i18n="common.error">Хатолик</div>`;
            window.i18n.applyTranslations();
        }
    }

    /**
     * Загружает уведомления.
     *
     * @param {HTMLElement} container - Контейнер
     */
    async loadNotifications(container) {
        const contentEl = container.querySelector('#messages-content');
        
        try {
            const data = await window.api.request('/messaging/notifications/');
            
            if (data && data.length > 0) {
                const unreadCount = data.filter(n => n.is_unread).length;
                
                contentEl.innerHTML = `
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                        <span data-i18n="messages.unread_count">Ўқилмаган: ${unreadCount}</span>
                        ${unreadCount > 0 ? `
                            <button id="mark-all-read-btn" class="btn btn-sm btn-success" data-i18n="messages.mark_all_read">Ҳаммасини ўқиш</button>
                        ` : ''}
                    </div>
                    <div class="card">
                        ${data.map(n => `
                            <div style="padding: 15px; border-bottom: 1px solid #eee; ${n.is_unread ? 'background-color: #f0f8ff;' : ''}">
                                <div style="display: flex; justify-content: space-between;">
                                    <strong>${n.type_display}</strong>
                                    <small>${new Date(n.created_at).toLocaleString()}</small>
                                </div>
                                <div style="margin-top: 5px;">${n.title}</div>
                                <div style="margin-top: 5px; color: #666;">${n.message}</div>
                                ${n.is_unread ? `
                                    <button class="btn btn-sm btn-success" style="margin-top: 10px;" onclick="window.messages.markNotificationRead(${n.id})">
                                        <span data-i18n="messages.mark_read">Ўқиш</span>
                                    </button>
                                ` : ''}
                            </div>
                        `).join('')}
                    </div>
                `;
            } else {
                contentEl.innerHTML = `<div class="card" style="padding: 20px; text-align: center;" data-i18n="messages.no_notifications">Уведомления йўқ</div>`;
            }
            window.i18n.applyTranslations();
            
            const markAllBtn = contentEl.querySelector('#mark-all-read-btn');
            if (markAllBtn) {
                markAllBtn.addEventListener('click', () => this.markAllNotificationsRead(container));
            }
        } catch (e) {
            console.error('Failed to load notifications', e);
            contentEl.innerHTML = `<div class="card" style="padding: 20px; text-align: center; color: red;" data-i18n="common.error">Хатолик</div>`;
            window.i18n.applyTranslations();
        }
    }

    /**
     * Настраивает обработчики событий.
     *
     * @param {HTMLElement} container - Контейнер
     */
    setupEventListeners(container) {
        const tab = container.querySelector('#messages-tab');
        tab.addEventListener('change', (e) => {
            if (e.target.value === 'inbox') {
                this.loadInbox(container);
            } else if (e.target.value === 'sent') {
                this.loadSent(container);
            } else {
                this.loadNotifications(container);
            }
        });

        // Сохраняем ссылку на компонент для глобального доступа
        window.messages = this;
        window.messages.container = container;
    }

    /**
     * Показывает модальное окно для составления сообщения.
     *
     * @param {HTMLElement} container - Контейнер
     */
    async showComposeModal(container) {
        // Загрузка пользователей
        let users = [];
        try {
            users = await window.api.request('/accounts/users/');
        } catch (e) {
            console.error('Failed to load users', e);
        }

        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.style.display = 'block';
        modal.innerHTML = `
            <div class="modal-content">
                <div class="modal-header">
                    <h3 data-i18n="messages.compose">Хабар юбориш</h3>
                    <button class="close">&times;</button>
                </div>
                <div class="modal-body">
                    <form id="compose-form">
                        <div class="form-group">
                            <label data-i18n="messages.to">Кимга</label>
                            <select name="recipient" class="form-control">
                                <option value="">Группа (барча)</option>
                                ${users.map(u => `<option value="${u.id}">${u.username} (${u.full_name || ''}) - ${u.role}</option>`).join('')}
                            </select>
                        </div>
                        <div class="form-group">
                            <label data-i18n="messages.subject">Мавзу</label>
                            <input type="text" name="subject" class="form-control">
                        </div>
                        <div class="form-group">
                            <label data-i18n="messages.content">Мазмун</label>
                            <textarea name="content" class="form-control" rows="5" required></textarea>
                        </div>
                        <button type="submit" class="btn btn-primary" data-i18n="messages.send">Юбориш</button>
                    </form>
                </div>
            </div>
        `;

        document.body.appendChild(modal);
        window.i18n.applyTranslations();

        modal.querySelector('.close').addEventListener('click', () => modal.remove());
        modal.addEventListener('click', (e) => {
            if (e.target === modal) modal.remove();
        });

        modal.querySelector('#compose-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const data = Object.fromEntries(formData);
            
            // Если recipient пустой, отправляем как групповое сообщение
            if (!data.recipient) {
                data.is_group = true;
                delete data.recipient;
            }
            
            try {
                await window.api.request('/messaging/messages/', {
                    method: 'POST',
                    body: JSON.stringify(data)
                });
                modal.remove();
                await this.loadInbox(container);
            } catch (error) {
                window.toast.error(error.data?.detail || 'Failed to send message');
            }
        });
    }

    /**
     * Просматривает сообщение.
     *
     * @param {number} messageId - ID сообщения
     */
    async viewMessage(messageId) {
        try {
            const message = await window.api.request(`/messaging/messages/${messageId}/`);
            
            const modal = document.createElement('div');
            modal.className = 'modal';
            modal.style.display = 'block';
            modal.innerHTML = `
                <div class="modal-content">
                    <div class="modal-header">
                        <h3>${message.subject || '(без темы)'}</h3>
                        <button class="close">&times;</button>
                    </div>
                    <div class="modal-body">
                        <p><strong data-i18n="messages.from">Кимдан:</strong> ${message.sender_name}</p>
                        <p><strong data-i18n="messages.to">Кимга:</strong> ${message.recipient_name || 'Группа'}</p>
                        <p><strong data-i18n="messages.date">Сана:</strong> ${new Date(message.created_at).toLocaleString()}</p>
                        <hr style="margin: 15px 0;">
                        <div style="white-space: pre-wrap;">${message.content}</div>
                    </div>
                </div>
            `;

            document.body.appendChild(modal);

            modal.querySelector('.close').addEventListener('click', () => modal.remove());
            modal.addEventListener('click', (e) => {
                if (e.target === modal) modal.remove();
            });
        } catch (error) {
            window.toast.error(error.data?.detail || 'Failed to load message');
        }
    }

    /**
     * Отмечает сообщение как прочитанное.
     *
     * @param {number} messageId - ID сообщения
     */
    async markRead(messageId) {
        try {
            await window.api.request(`/messaging/messages/${messageId}/mark_read/`, {
                method: 'POST'
            });
            await this.loadInbox(this.container);
        } catch (error) {
            window.toast.error(error.data?.detail || 'Failed to mark message as read');
        }
    }

    /**
     * Отмечает уведомление как прочитанное.
     *
     * @param {number} notificationId - ID уведомления
     */
    async markNotificationRead(notificationId) {
        try {
            await window.api.request(`/messaging/notifications/${notificationId}/mark_read/`, {
                method: 'POST'
            });
            await this.loadNotifications(this.container);
        } catch (error) {
            window.toast.error(error.data?.detail || 'Failed to mark notification as read');
        }
    }

    /**
     * Отмечает все уведомления как прочитанные.
     *
     * @param {HTMLElement} container - Контейнер
     */
    async markAllNotificationsRead(container) {
        try {
            await window.api.request('/messaging/notifications/mark_all_read/', {
                method: 'POST'
            });
            await this.loadNotifications(container);
        } catch (error) {
            window.toast.error(error.data?.detail || 'Failed to mark all notifications as read');
        }
    }
}

window.MessagesComponent = new MessagesComponent();
