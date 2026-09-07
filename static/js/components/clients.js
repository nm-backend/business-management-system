/**
 * Клиенты: активные / архив, красная карточка при долге,
 * owner видит суммы и историю оплат, admin - только статусы.
 */
class ClientsComponent {
    async render(container) {
        document.getElementById('page-title').setAttribute('data-i18n', 'clients.title');
        this.currentTab = 'active';
        const canEdit = window.currentUser.is_owner || window.currentUser.is_admin;

        // Панель мониторинга долгов для владельца
        const debtDashboard = window.currentUser.is_owner ? `
            <div id="debt-monitoring" style="display:none;margin-bottom:14px;">
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;">
                    <div class="card" style="margin:0;padding:12px;border-left:4px solid var(--danger-color);">
                        <div class="text-sm text-muted">Кардорли мижозлар</div>
                        <div style="font-weight:700;font-size:20px;color:var(--danger-color);" id="debt-clients-count">0 та</div>
                    </div>
                    <div class="card" style="margin:0;padding:12px;border-left:4px solid var(--warning-color, #f59e0b);">
                        <div class="text-sm text-muted">Жами карз суммаси</div>
                        <div style="font-weight:700;font-size:20px;color:var(--warning-color, #f59e0b);" id="debt-total-amount">0 сум</div>
                    </div>
                </div>
            </div>` : '';

        container.innerHTML = `
            ${debtDashboard}
            <div class="tabs">
                <button class="tab-btn active" data-tab="active" data-i18n="clients.active"></button>
                <button class="tab-btn" data-tab="archive" data-i18n="clients.archive"></button>
            </div>
            <div class="search-box">
                <span class="search-icon" aria-hidden="true">🔍</span>
                <input type="text" id="client-search" class="form-control" data-i18n-attr="placeholder,aria-label" data-i18n="clients.search_hint">
            </div>
            ${canEdit ? `<button class="btn btn-primary btn-block" id="add-client-btn" style="margin-bottom:12px;" data-i18n="clients.add_client"></button>` : ''}
            <div id="clients-list" class="card-grid"></div>
        `;

        container.querySelectorAll('.tab-btn').forEach((btn) => {
            btn.addEventListener('click', () => {
                container.querySelectorAll('.tab-btn').forEach((b) => b.classList.remove('active'));
                btn.classList.add('active');
                this.currentTab = btn.dataset.tab;
                this.loadClients();
            });
        });

        const searchInput = container.querySelector('#client-search');
        searchInput.addEventListener('input', window.ui.debounce(() => {
            this.loadClients(searchInput.value);
        }, 300));

        if (canEdit) {
            container.querySelector('#add-client-btn').addEventListener('click', () => this.openForm());
        }

        window.i18n.applyTranslations();
        await this.loadDebtMonitoring();
        await this.loadClients();
    }

    /** Панель мониторинга долгов (только для владельца) */
    async loadDebtMonitoring() {
        const panel = document.getElementById('debt-monitoring');
        if (!panel || !window.currentUser.is_owner) return;
        try {
            const response = await window.api.request('/clients/clients/?is_archived=false');
            const clients = response.results || response;
            const debtClients = clients.filter(c => c.has_debt && c.debt > 0);
            const totalDebt = debtClients.reduce((sum, c) => sum + (c.debt || 0), 0);
            panel.style.display = 'block';
            document.getElementById('debt-clients-count').textContent = `${debtClients.length} та`;
            document.getElementById('debt-total-amount').textContent = window.ui.money(totalDebt);
        } catch (e) {
            // Панель некритична
        }
    }

    async loadClients(search = '') {
        const listEl = document.getElementById('clients-list');
        // Пользователь мог уйти со страницы, пока шёл запрос: контейнера
        // больше нет, рисовать некуда.
        if (window.listStates.gone(listEl)) return;
        window.listStates.skeleton(listEl);
        try {
            let query = `?is_archived=${this.currentTab === 'archive'}`;
            if (search) query += `&search=${encodeURIComponent(search)}`;
            const response = await window.api.request(`/clients/clients/${query}`);
            this.clients = response.results || response;

            if (!this.clients.length) {
                const canEdit = window.currentUser?.is_owner || window.currentUser?.is_admin;
                const cta = canEdit ? `<button type="button" class="btn btn-primary btn-sm" id="empty-add-client" data-i18n="clients.add_client"></button>` : '';
                window.listStates.empty(listEl, window.ui.t('common.no_data'), cta);
                const btn = listEl.querySelector('#empty-add-client');
                if (btn) btn.addEventListener('click', () => this.openForm());
                window.i18n.applyTranslations();
                return;
            }
            listEl.innerHTML = this.clients.map((c) => this.renderCard(c)).join('');
            listEl.querySelectorAll('[data-id]').forEach((card) => {
                card.addEventListener('click', () => {
                    const client = this.clients.find((c) => c.id === Number(card.dataset.id));
                    this.openDetail(client);
                });
                card.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        card.click();
                    }
                });
            });
            window.i18n.applyTranslations();
        } catch (e) {
            window.listStates.error(listEl, window.ui.t('common.error'), () => this.loadClients(search));
        }
    }

    renderCard(c) {
        const debtHtml = c.debt !== undefined && c.has_debt
            ? `<div style="font-size:16px;font-weight:700;margin-top:4px;" class="text-danger">${window.ui.money(c.debt)}</div>`
            : '';
        return `
            <div class="card" role="button" tabindex="0" data-id="${c.id}" style="cursor:pointer;border-left:4px solid ${c.has_debt ? 'var(--danger-color)' : 'var(--success-color)'};">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;">
                    <div style="min-width:0;">
                        <div style="font-size:15px;font-weight:600;">${window.ui.escape(c.name)}</div>
                        ${c.phone ? `<div class="text-sm text-muted">${window.ui.escape(c.phone)}</div>` : ''}
                        ${debtHtml}
                    </div>
                    <span class="badge ${c.has_debt ? 'badge-cancel' : 'badge-ready'}"
                        data-i18n="payment_statuses.${c.has_debt ? 'unpaid' : 'paid'}"></span>
                </div>
            </div>`;
    }

    openDetail(c) {
        const user = window.currentUser;
        const canEdit = user.is_owner || user.is_admin;
        const row = (labelKey, valueHtml, danger = false) => (!valueHtml ? '' : `
            <div class="list-row" style="cursor:default;">
                <span class="text-sm text-muted" data-i18n="${labelKey}"></span>
                <span class="text-sm font-bold ${danger ? 'text-danger' : ''}" style="text-align:right;">${valueHtml}</span>
            </div>`);

        const payments = (c.payments || []).slice(0, 10).map((p) => `
            <div class="list-row" style="cursor:default;">
                <span class="text-sm text-muted">${window.ui.datetime(p.payment_date)}</span>
                <span class="text-sm font-bold text-success">+${window.ui.money(p.amount)}</span>
            </div>`).join('');

        const modal = window.ui.modal(c.name, `
            ${c.has_debt ? `<div class="alert-box">⚠️ <span data-i18n="clients.not_paid_warning"></span></div>` : ''}
            <div style="display:flex;gap:4px;margin-bottom:12px;" class="tabs" id="client-detail-tabs">
                <button class="tab-btn active" data-client-tab="info" data-i18n="clients.info"></button>
                <button class="tab-btn" data-client-tab="orders" data-i18n="clients.orders"></button>
                ${user.is_owner ? `<button class="tab-btn" data-client-tab="payments" data-i18n="clients.payment_history"></button>` : ''}
                ${user.is_owner ? `<button class="tab-btn" data-client-tab="debts" data-i18n="clients.debts"></button>` : ''}
            </div>
            <div id="client-tab-content">
                <div class="list-group" style="box-shadow:none;border:1px solid var(--border);">
                    ${row('clients.name', window.ui.escape(c.name))}
                    ${row('clients.phone', window.ui.escape(c.phone || ''))}
                    ${row('clients.address', window.ui.escape(c.address || ''))}
                    ${user.is_owner ? row('clients.total_amount', window.ui.money(c.total_orders_amount)) : ''}
                    ${user.is_owner ? row('clients.paid', window.ui.money(c.total_paid)) : ''}
                    ${user.is_owner ? row('clients.debt', window.ui.money(c.debt), c.has_debt) : ''}
                    ${user.is_owner ? row('clients.profit',
                        `<span class="${Number(c.profit) < 0 ? 'text-danger' : ''}" style="${Number(c.profit) >= 0 ? 'color:var(--success-color);' : ''}">${window.ui.money(c.profit)}</span>`,
                        Number(c.profit) < 0) : ''}
                    ${row('common.status', `<span class="badge ${c.has_debt ? 'badge-cancel' : 'badge-ready'}" data-i18n="payment_statuses.${c.has_debt ? 'unpaid' : 'paid'}"></span>`)}
                    ${row('warehouse.comment', window.ui.escape(c.comment || ''))}
                </div>
            </div>
            <div style="display:flex;gap:10px;margin-top:14px;">
                ${canEdit ? `<button class="btn btn-secondary btn-sm" id="edit-client" style="flex:1;" data-i18n="common.edit"></button>` : ''}
                ${canEdit ? `<button class="btn btn-secondary btn-sm btn-block" id="archive-client" style="margin-top:10px;"
                    data-i18n="${c.is_archived ? 'common.restore' : 'common.archive'}"></button>` : ''}
            </div>
        `);

        const editBtn = modal.querySelector('#edit-client');
        if (editBtn) editBtn.addEventListener('click', () => {
            window.ui.closeModal(modal);
            this.openForm(c);
        });
        // Client detail tabs
        modal.querySelectorAll('[data-client-tab]').forEach(tab => {
            tab.addEventListener('click', () => {
                modal.querySelectorAll('[data-client-tab]').forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                const tabName = tab.dataset.clientTab;
                const contentEl = modal.querySelector('#client-tab-content');
                if (tabName === 'orders') {
                    window.router.navigate(`/orders?client=${c.id}`);
                    return;
                }
                if (tabName === 'payments') {
                    contentEl.innerHTML = `<div class="list-group" style="box-shadow:none;border:1px solid var(--border);">${payments || '<div class="text-sm text-muted" style="padding:12px;text-align:center;">' + window.ui.t('common.no_data') + '</div>'}</div>`;
                } else if (tabName === 'debts') {
                    const debtInfo = c.has_debt ? 
                        `<div class="list-group" style="box-shadow:none;border:1px solid var(--border);">
                            <div class="list-row" style="cursor:default;">
                                <span class="text-sm text-muted" data-i18n="clients.total_amount"></span>
                                <span class="text-sm font-bold">${window.ui.money(c.total_orders_amount)}</span>
                            </div>
                            <div class="list-row" style="cursor:default;">
                                <span class="text-sm text-muted" data-i18n="clients.paid"></span>
                                <span class="text-sm font-bold text-success">${window.ui.money(c.total_paid)}</span>
                            </div>
                            <div class="list-row" style="cursor:default;">
                                <span class="text-sm text-muted" data-i18n="clients.debt"></span>
                                <span class="text-sm font-bold text-danger">${window.ui.money(c.debt)}</span>
                            </div>
                        </div>` : 
                        `<div class="text-sm text-muted" style="padding:12px;text-align:center;">✅ ${window.ui.t('clients.no_debt')}</div>`;
                    contentEl.innerHTML = debtInfo;
                } else {
                    contentEl.innerHTML = `<div class="list-group" style="box-shadow:none;border:1px solid var(--border);">
                        ${row('clients.name', window.ui.escape(c.name))}
                        ${row('clients.phone', window.ui.escape(c.phone || ''))}
                        ${row('clients.address', window.ui.escape(c.address || ''))}
                        ${window.currentUser.is_owner ? row('clients.total_amount', window.ui.money(c.total_orders_amount)) : ''}
                        ${window.currentUser.is_owner ? row('clients.paid', window.ui.money(c.total_paid)) : ''}
                        ${window.currentUser.is_owner ? row('clients.debt', window.ui.money(c.debt), c.has_debt) : ''}
                        ${window.currentUser.is_owner ? row('clients.profit',
                            `<span class="${Number(c.profit) < 0 ? 'text-danger' : ''}" style="${Number(c.profit) >= 0 ? 'color:var(--success-color);' : ''}">${window.ui.money(c.profit)}</span>`,
                            Number(c.profit) < 0) : ''}
                        ${row('common.status', `<span class="badge ${c.has_debt ? 'badge-cancel' : 'badge-ready'}" data-i18n="payment_statuses.${c.has_debt ? 'unpaid' : 'paid'}"></span>`)}
                        ${row('warehouse.comment', window.ui.escape(c.comment || ''))}
                    </div>`;
                }
                window.i18n.applyTranslations();
            });
        });
        // Вкладка «Архив» была только на чтение: убрать клиента в архив или
        // вернуть его оттуда из интерфейса было нечем.
        const archiveBtn = modal.querySelector('#archive-client');
        if (archiveBtn) archiveBtn.addEventListener('click', async () => {
            if (!c.is_archived && !(await window.confirmation.confirm(
                window.ui.t('common.archive_confirm'), window.ui.t('common.archive')))) return;
            try {
                await window.api.request(
                    `/clients/clients/${c.id}/${c.is_archived ? 'restore' : 'archive'}/`,
                    { method: 'POST' },
                );
                window.ui.closeModal(modal);
                window.toast.success(window.ui.t('common.success'));
                await this.loadClients();
            } catch (error) {
                window.toast.error(window.ui.errorText(error));
            }
        });
    }

    openForm(c = null) {
        const modal = window.ui.modal(c ? 'common.edit' : 'clients.add_client', `
            <form id="client-form">
                <div class="form-group"><label data-i18n="clients.name"></label>
                    <input name="name" class="form-control" required value="${window.ui.escape(c?.name || '')}"></div>
                <div class="form-group"><label data-i18n="clients.phone"></label>
                    <!-- Тот же формат, что валидирует сервер (validate_phone):
                         только цифры, +, ( ), - и пробелы. Раньше форму можно
                         было отправить с любым мусором, а ошибку показывал
                         только сервер после отправки. -->
                    <input name="phone" class="form-control" value="${window.ui.escape(c?.phone || '')}"
                           pattern="(?:[0-9+\\x28\\x29 \\u002D]*[0-9]){5,}[0-9+\\x28\\x29 \\u002D]*" title="${window.ui.t('clients.phone_hint')}"></div>
                <div class="form-group"><label data-i18n="clients.address"></label>
                    <textarea name="address" class="form-control" rows="2">${window.ui.escape(c?.address || '')}</textarea></div>
                <div class="form-group"><label data-i18n="warehouse.comment"></label>
                    <textarea name="comment" class="form-control" rows="2">${window.ui.escape(c?.comment || '')}</textarea></div>
                <button type="submit" class="btn btn-primary btn-block" data-i18n="common.save"></button>
            </form>
        `);

        modal.querySelector('#client-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target));
            await window.ui.submitGuard(e.target.querySelector('button[type=submit]'), async () => {
                try {
                    if (c) {
                        await window.api.request(`/clients/clients/${c.id}/`, { method: 'PATCH', body: JSON.stringify(data) });
                    } else {
                        await window.api.request('/clients/clients/', { method: 'POST', body: JSON.stringify(data) });
                    }
                    window.ui.closeModal(modal);
                    window.toast.success(window.ui.t('common.success'));
                    await this.loadClients();
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        });
    }
}

window.ClientsComponent = new ClientsComponent();
