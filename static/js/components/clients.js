/**
 * Компонент для управления клиентами.
 *
 * Отображает список клиентов, позволяет создавать, редактировать и архивировать клиентов.
 * Поддерживает фильтрацию по активным и архивным клиентам.
 */
class ClientsComponent {
    /**
     * Рендерит страницу клиентов.
     *
     * @param {HTMLElement} container - Контейнер для рендеринга
     */
    async render(container) {
        container.innerHTML = `
            <header style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                <h1 data-i18n="clients.title">Мижозлар</h1>
                <div style="display: flex; gap: 10px;">
                    <select id="client-filter" class="form-control" style="width: auto;">
                        <option value="active" data-i18n="clients.active">Актив</option>
                        <option value="archived" data-i18n="clients.archived">Архив</option>
                        <option value="all" data-i18n="clients.all">Барча</option>
                    </select>
                    <button id="add-client-btn" class="btn btn-primary" data-i18n="clients.add_client">Қўшиш</button>
                </div>
            </header>
            
            <div class="card" style="overflow-x: auto;">
                <table style="width: 100%; border-collapse: collapse; text-align: left;">
                    <thead>
                        <tr style="border-bottom: 2px solid #eee;">
                            <th style="padding: 10px;" data-i18n="clients.name">Исм</th>
                            <th style="padding: 10px;" data-i18n="clients.phone">Телефон</th>
                            <th style="padding: 10px;" data-i18n="clients.address">Манзил</th>
                            <th style="padding: 10px;" data-i18n="clients.status">Ҳолат</th>
                            <th style="padding: 10px;" data-i18n="clients.has_debt">Қарз</th>
                            <th style="padding: 10px;" data-i18n="common.actions">Амаллар</th>
                        </tr>
                    </thead>
                    <tbody id="clients-list">
                        <tr><td colspan="6" style="padding: 10px; text-align: center;" data-i18n="common.loading">Юкланмоқда...</td></tr>
                    </tbody>
                </table>
            </div>
        `;

        await this.loadClients(container);
        this.setupEventListeners(container);
    }

    /**
     * Загружает список клиентов с сервера.
     *
     * @param {HTMLElement} container - Контейнер
     */
    async loadClients(container) {
        const listEl = container.querySelector('#clients-list');
        const filter = container.querySelector('#client-filter').value;
        window.listStates.tableLoading(listEl, 6);
        
        try {
            let url = '/clients/';
            if (filter === 'active') {
                url += 'active/';
            } else if (filter === 'archived') {
                url += 'archived/';
            }
            
            const data = await window.api.request(url);
            
            if (data && data.length > 0) {
                listEl.innerHTML = data.map(c => `
                    <tr style="border-bottom: 1px solid #eee;">
                        <td style="padding: 10px;">${c.name}</td>
                        <td style="padding: 10px;">${c.phone || '-'}</td>
                        <td style="padding: 10px;">${c.address || '-'}</td>
                        <td style="padding: 10px;">
                            <span class="badge ${c.is_active ? 'badge-success' : 'badge-secondary'}">
                                ${(window.i18n && window.i18n.translate) ? (c.is_active ? (c.is_archived ? window.i18n.translate('clients.archived_label') : window.i18n.translate('clients.active_label')) : window.i18n.translate('clients.inactive_label')) : (c.is_active ? (c.is_archived ? 'Архив' : 'Актив') : 'Неактив')}
                            </span>
                        </td>
                        <td style="padding: 10px;">
                            ${c.has_debt ? '<span style="color: red;">' + ((window.i18n && window.i18n.translate) ? window.i18n.translate('clients.has_debt_label') : 'Қарз бор') + '</span>' : '-'}
                        </td>
                        <td style="padding: 10px;">
                            <button class="btn btn-sm btn-info" onclick="window.router.navigate('#clients/${c.id}')">
                                <span data-i18n="common.view">Кўриш</span>
                            </button>
                            ${!c.is_archived ? `<button class="btn btn-sm btn-danger archive-client" data-id="${c.id}">${(window.i18n && window.i18n.translate) ? window.i18n.translate('clients.archive_btn') : 'Archive'}</button>` : ''}
                        </td>
                    </tr>
                `).join('');
            } else {
                window.listStates.tableEmpty(listEl, 6, 'No clients found');
            }
            window.i18n.applyTranslations();
        } catch (e) {
            console.error('Failed to load clients', e);
            window.listStates.tableError(listEl, 6, 'Unable to load clients', () => this.loadClients(container));
            window.i18n.applyTranslations();
        }
    }

    /**
     * Настраивает обработчики событий.
     *
     * @param {HTMLElement} container - Контейнер
     */
    setupEventListeners(container) {
        const filter = container.querySelector('#client-filter');
        filter.addEventListener('change', () => this.loadClients(container));

        const addBtn = container.querySelector('#add-client-btn');
        if (addBtn) {
            addBtn.addEventListener('click', () => this.showAddClientModal(container));
        }

        // Используем делегирование для archive кнопок и удаляем старый listener
        if (this._archiveHandler) {
            container.removeEventListener('click', this._archiveHandler);
        }
        this._archiveHandler = async (event) => {
            const button = event.target.closest('.archive-client');
            if (!button) return;
            if (!await window.confirmation.confirm('Архивга юбориш?')) return;
            try {
                await window.api.request(`/clients/${button.dataset.id}/archive/`, { method: 'POST' });
                window.toast.success('Мижоз архивланди');
                await this.loadClients(container);
            } catch (error) {
                window.toast.error(error.data?.detail || 'Архивлаш хатоси');
            }
        };
        container.addEventListener('click', this._archiveHandler);
    }

    /**
     * Показывает модальное окно для добавления клиента.
     *
     * @param {HTMLElement} container - Контейнер
     */
    showAddClientModal(container) {
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.style.display = 'block';
        modal.innerHTML = `
            <div class="modal-content">
                <div class="modal-header">
                    <h3 data-i18n="clients.add_client">Янги мижоз</h3>
                    <button class="close">&times;</button>
                </div>
                <div class="modal-body">
                    <form id="add-client-form">
                        <div class="form-group">
                            <label data-i18n="clients.name">Исм</label>
                            <input type="text" name="name" class="form-control" required>
                        </div>
                        <div class="form-group">
                            <label data-i18n="clients.phone">Телефон</label>
                            <input type="text" name="phone" class="form-control">
                        </div>
                        <div class="form-group">
                            <label data-i18n="clients.address">Манзил</label>
                            <textarea name="address" class="form-control" rows="3"></textarea>
                        </div>
                        <div class="form-group">
                            <label data-i18n="clients.notes">Изоҳлар</label>
                            <textarea name="notes" class="form-control" rows="3"></textarea>
                        </div>
                        <button type="submit" class="btn btn-primary" data-i18n="common.save">Сақлаш</button>
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

        modal.querySelector('#add-client-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const data = Object.fromEntries(formData);
            
            try {
                await window.api.request('/clients/', {
                    method: 'POST',
                    body: JSON.stringify(data)
                });
                modal.remove();
                window.toast.success('Мижоз яратилди');
                await this.loadClients(container);
            } catch (error) {
                window.toast.error(error.data?.detail || 'Мижоз қўшиш хатоси');
            }
        });
    }
}

window.ClientsComponent = new ClientsComponent();
