/**
 * Клиенты: активные / архив, красная карточка при долге,
 * owner видит суммы и историю оплат, admin - только статусы.
 */
class ClientsComponent {
    async render(container) {
        document.getElementById('page-title').setAttribute('data-i18n', 'clients.title');
        this.currentTab = 'active';
        const canEdit = window.currentUser.is_owner || window.currentUser.is_admin;

        // Панель мониторинга долгов для владельца. Бакеты просрочки
        // («1–7 / 8–14 / 15+ / срок не вышел») считает сервер в debt_summary.
        const debtDashboard = window.currentUser.is_owner ? `
            <div id="debt-monitoring" style="display:none;margin-bottom:14px;">
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;">
                    <div class="card" style="margin:0;padding:12px;border-left:4px solid var(--danger-color);">
                        <div class="text-sm text-muted" data-i18n="clients.debtors"></div>
                        <div style="font-weight:700;font-size:20px;color:var(--danger-color);" id="debt-clients-count">—</div>
                    </div>
                    <div class="card" style="margin:0;padding:12px;border-left:4px solid var(--warning-color, #f59e0b);">
                        <div class="text-sm text-muted" data-i18n="clients.total_debt"></div>
                        <div style="font-weight:700;font-size:20px;color:var(--warning-color, #f59e0b);" id="debt-total-amount">—</div>
                    </div>
                </div>
                <div class="text-sm text-muted u-hint" data-i18n="clients.overdue_control"></div>
                <div id="debt-buckets" class="u-grid-2"></div>
                <div id="debt-hot-list"></div>
            </div>` : '';

        container.innerHTML = `
            ${debtDashboard}
            <!-- Вкладки списка из макета «Мижозлар»: все / активные /
                 с долгом / новые / архив. Фильтрует сервер (?is_active_client=,
                 ?has_debt=, ?is_new=, ?is_archived=) — отбор загруженной страницы
                 показывал бы неверные списки при пагинации. -->
            <div class="tabs">
                <button class="tab-btn" data-tab="all" data-i18n="common.all"></button>
                <button class="tab-btn active" data-tab="active" data-i18n="clients.active"></button>
                <button class="tab-btn" data-tab="debt" data-i18n="clients.has_debt"></button>
                <button class="tab-btn" data-tab="new" data-i18n="clients.new"></button>
                <button class="tab-btn" data-tab="archive" data-i18n="clients.archive"></button>
            </div>
            <div class="search-box">
                <span class="search-icon" aria-hidden="true">${window.icon('search', 18)}</span>
                <input type="text" id="client-search" class="form-control" data-i18n-attr="placeholder,aria-label" data-i18n="clients.search_hint">
            </div>
            ${canEdit ? `<button class="btn btn-primary btn-block u-mb-5" id="add-client-btn" data-i18n="clients.add_client"></button>` : ''}
            <div class="text-sm text-muted u-hint" id="clients-listed-count"></div>
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
            // Считает сервер: сумма долга приходит строкой (Decimal), и
            // складывать её в JS нельзя — получалась конкатенация и NaN;
            // плюс список клиентов постраничный, в сумму попадала только
            // первая страница.
            const summary = await window.api.request('/clients/clients/debt_summary/');
            panel.style.display = 'block';
            document.getElementById('debt-clients-count').textContent =
                `${summary.debtors_count} ${window.ui.t('common.pcs_short')}`;
            document.getElementById('debt-total-amount').textContent =
                window.ui.money(summary.total_debt);

            const buckets = summary.buckets || {};
            const defs = [
                ['not_due', 'clients.not_due', 'var(--success-color)'],
                ['overdue_1_7', 'clients.overdue_1_7', 'var(--warning-color, #f59e0b)'],
                ['overdue_8_14', 'clients.overdue_8_14', 'var(--warning-color, #f59e0b)'],
                ['overdue_15_plus', 'clients.overdue_15_plus', 'var(--danger-color)'],
            ];
            const bucketsEl = document.getElementById('debt-buckets');
            if (bucketsEl) {
                bucketsEl.innerHTML = defs.map(([key, label, color]) => {
                    const b = buckets[key] || { count: 0, total: 0 };
                    return `
                        <div class="card" data-debt-bucket="${key}"
                             style="margin:0;padding:12px;border-left:4px solid ${color};cursor:pointer;">
                            <div class="text-sm text-muted" data-i18n="${label}"></div>
                            <div style="font-weight:700;font-size:16px;">${b.count} ${window.ui.t('common.pcs_short')}</div>
                            <div class="text-sm" style="color:${color};">${window.ui.money(b.total)}</div>
                        </div>`;
                }).join('');
                bucketsEl.querySelectorAll('[data-debt-bucket]').forEach((el) => {
                    el.addEventListener('click', () => {
                        const btn = document.querySelector('.tab-btn[data-tab="debt"]');
                        if (btn) btn.click();
                    });
                });
            }
            const hotEl = document.getElementById('debt-hot-list');
            const hot = (buckets.overdue_15_plus && buckets.overdue_15_plus.orders) || [];
            if (hotEl) {
                if (!hot.length) {
                    hotEl.innerHTML = '';
                } else {
                    hotEl.innerHTML = `
                        <div class="list-group list-group-compact u-mt-4">
                            ${hot.slice(0, 5).map((o) => `
                                <a class="list-row u-plain-link" href="#/orders?client=${o.client}">
                                    <div class="u-minw-0">
                                        <div class="u-strong">${window.ui.escape(o.client_name || '')}</div>
                                        <div class="text-sm text-muted">#${o.order} · ${o.days_overdue} ${window.ui.t('companies.days_left')}</div>
                                    </div>
                                    <span class="font-bold text-danger">${window.ui.money(o.debt)}</span>
                                </a>`).join('')}
                        </div>`;
                }
            }
            window.i18n.applyTranslations();
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
            // Каждая вкладка — свой серверный фильтр. «Все» показывает
            // действующих клиентов (архив выделен в отдельную вкладку).
            const tab = this.currentTab || 'active';
            let query = `?is_archived=${tab === 'archive'}`;
            if (tab === 'active') query += '&is_active_client=true';
            if (tab === 'debt') query += '&has_debt=true';
            if (tab === 'new') query += '&is_new=true';
            if (search) query += `&search=${encodeURIComponent(search)}`;
            const response = await window.api.request(`/clients/clients/${query}`);
            this.clients = response.results || response;
            const total = response.count ?? this.clients.length;
            const countEl = document.getElementById('clients-listed-count');
            if (countEl) {
                countEl.textContent = `${window.ui.t('common.total')}: ${total} ${window.ui.t('common.pcs_short')}`;
            }

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
                    <div class="u-minw-0">
                        <div class="u-title-md">${window.ui.escape(c.name)}</div>
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
            <div class="list-row u-cursor-default">
                <span class="text-sm text-muted" data-i18n="${labelKey}"></span>
                <span class="text-sm font-bold ${danger ? 'text-danger' : ''} u-text-right">${valueHtml}</span>
            </div>`);

        // Вкладка «Умумий» из макета «Мижоз картаси». Финансовые строки
        // рисуются только владельцу, но и API администратору их не отдаёт:
        // c.debt/c.total_paid в его payload попросту отсутствуют.
        const infoTab = () => `
            <div class="list-group u-card-flat">
                ${row('clients.name', window.ui.escape(c.name))}
                ${row('clients.phone', window.ui.escape(c.phone || ''))}
                ${row('clients.address', window.ui.escape(c.address || ''))}
                ${row('clients.added_date', c.created_at ? window.ui.date(c.created_at) : '')}
                ${row('clients.client_type', c.client_type
                    ? `<span data-i18n="client_types.${c.client_type}"></span>` : '')}
                ${row('clients.responsible', window.ui.escape(c.responsible_employee_name || ''))}
                ${user.is_owner ? row('clients.total_amount', window.ui.money(c.total_orders_amount)) : ''}
                ${user.is_owner ? row('clients.paid', window.ui.money(c.total_paid)) : ''}
                ${user.is_owner ? row('clients.debt', window.ui.money(c.debt), c.has_debt) : ''}
                ${user.is_owner ? row('clients.profit',
                    `<span class="${Number(c.profit) < 0 ? 'text-danger' : ''}" style="${Number(c.profit) >= 0 ? 'color:var(--success-color);' : ''}">${window.ui.money(c.profit)}</span>`,
                    Number(c.profit) < 0) : ''}
                ${row('common.status', `<span class="badge ${c.has_debt ? 'badge-cancel' : 'badge-ready'}" data-i18n="payment_statuses.${c.has_debt ? 'unpaid' : 'paid'}"></span>`)}
                ${row('warehouse.comment', window.ui.escape(c.comment || ''))}
            </div>`;

        const payments = (c.payments || []).slice(0, 10).map((p) => `
            <div class="list-row u-cursor-default">
                <span class="text-sm text-muted">${window.ui.datetime(p.payment_date)}</span>
                <span class="text-sm font-bold text-success">+${window.ui.money(p.amount)}</span>
            </div>`).join('');

        const modal = window.ui.modal(c.name, `
            ${c.has_debt ? `<div class="alert-box">${window.icon('alert-triangle', 16)} <span data-i18n="clients.not_paid_warning"></span></div>` : ''}
            <div style="display:flex;gap:4px;margin-bottom:12px;" class="tabs" id="client-detail-tabs">
                <button class="tab-btn active" data-client-tab="info" data-i18n="clients.info"></button>
                <button class="tab-btn" data-client-tab="orders" data-i18n="clients.orders"></button>
                ${user.is_owner ? `<button class="tab-btn" data-client-tab="payments" data-i18n="clients.payment_history"></button>` : ''}
                ${user.is_owner ? `<button class="tab-btn" data-client-tab="debts" data-i18n="clients.debts"></button>` : ''}
            </div>
            <div id="client-tab-content">${infoTab()}</div>
            <div style="display:flex;gap:10px;margin-top:14px;">
                ${canEdit ? `<button class="btn btn-secondary btn-sm u-grow" id="edit-client" data-i18n="common.edit"></button>` : ''}
                ${canEdit ? `<button class="btn btn-secondary btn-sm btn-block u-mt-4" id="archive-client"
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
                    // Заказы клиента показываем ВНУТРИ карточки (макет
                    // «Мижоз картаси» → вкладка «Заказлар»). Раньше вкладка
                    // уводила на общий список и карточка закрывалась.
                    // Данные настоящие: /orders/orders/?client=<id>.
                    // Суммы в ответе есть только у владельца — администратору
                    // их не отдаёт сам API, а не прячет интерфейс.
                    contentEl.innerHTML = `<div class="list-state" data-i18n="common.loading"></div>`;
                    window.i18n.applyTranslations();
                    window.api.request(`/orders/orders/?client=${c.id}&page_size=50`)
                        .then((resp) => {
                            const orders = resp.results || resp;
                            const active = orders.filter(
                                (o) => !['delivered', 'cancelled'].includes(o.status)
                            ).length;
                            contentEl.innerHTML = `
                                <div class="text-sm text-muted u-mb-3">
                                    <span data-i18n="clients.active_orders"></span>: ${active}
                                </div>
                                <div class="list-group u-card-flat">
                                    ${orders.length ? orders.map((o) => `
                                        <div class="list-row u-cursor-default">
                                            <div class="u-minw-0">
                                                <div class="text-sm font-bold">#${o.id}
                                                    ${window.ui.escape(o.product_name || o.custom_product_name || '')}</div>
                                                <div class="text-sm text-muted">
                                                    ${window.ui.qty(o.quantity)}
                                                    <span data-i18n="units.${o.unit}"></span>
                                                    ${o.deadline ? ` · ${window.ui.date(o.deadline)}` : ''}
                                                </div>
                                            </div>
                                            <div class="u-text-right u-shrink-0">
                                                ${window.ui.orderBadge
                                                    ? window.ui.orderBadge(o.status)
                                                    : `<span class="badge" data-i18n="statuses.${o.status}"></span>`}
                                                ${o.total_amount !== undefined
                                                    ? `<div class="text-sm font-bold">${window.ui.money(o.total_amount)}</div>`
                                                    : ''}
                                            </div>
                                        </div>`).join('')
                                        : `<div class="text-sm text-muted u-p-3 u-text-center" data-i18n="common.no_data"></div>`}
                                </div>
                                <a class="btn btn-secondary btn-sm btn-block u-mt-4"
                                   href="#/orders?client=${c.id}" data-i18n="clients.open_all_orders"></a>`;
                            window.i18n.applyTranslations();
                        })
                        .catch(() => {
                            contentEl.innerHTML = `<div class="list-state" data-i18n="common.error"></div>`;
                            window.i18n.applyTranslations();
                        });
                    return;
                }
                if (tabName === 'payments') {
                    contentEl.innerHTML = `<div class="list-group u-card-flat">${payments || '<div class="text-sm text-muted u-p-3 u-text-center">' + window.ui.t('common.no_data') + '</div>'}</div>`;
                } else if (tabName === 'debts') {
                    const debtInfo = c.has_debt ? 
                        `<div class="list-group u-card-flat">
                            <div class="list-row u-cursor-default">
                                <span class="text-sm text-muted" data-i18n="clients.total_amount"></span>
                                <span class="text-sm font-bold">${window.ui.money(c.total_orders_amount)}</span>
                            </div>
                            <div class="list-row u-cursor-default">
                                <span class="text-sm text-muted" data-i18n="clients.paid"></span>
                                <span class="text-sm font-bold text-success">${window.ui.money(c.total_paid)}</span>
                            </div>
                            <div class="list-row u-cursor-default">
                                <span class="text-sm text-muted" data-i18n="clients.debt"></span>
                                <span class="text-sm font-bold text-danger">${window.ui.money(c.debt)}</span>
                            </div>
                        </div>` : 
                        `<div class="text-sm text-muted u-p-3 u-text-center">${window.icon('check-circle', 16)} ${window.ui.t('clients.no_debt')}</div>`;
                    contentEl.innerHTML = debtInfo;
                } else {
                    contentEl.innerHTML = infoTab();
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

    async openForm(c = null) {
        // Тип и ответственный уже есть в API и на карточке, но форма их
        // не принимала — поля можно было сменить только через PATCH вручную.
        let users = [];
        try {
            const resp = await window.api.request('/accounts/users/?is_active=true&page_size=100');
            users = resp.results || resp;
        } catch (e) {
            users = [];
        }
        const typeOptions = ['individual', 'company'].map((type) => `
            <option value="${type}" ${ (c?.client_type || 'individual') === type ? 'selected' : '' }
                    data-i18n="client_types.${type}"></option>`).join('');
        const userOptions = users.map((u) => `
            <option value="${u.id}" ${String(c?.responsible_employee) === String(u.id) ? 'selected' : ''}>
                ${window.ui.escape(u.full_name || u.username)}
            </option>`).join('');
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
                <div class="form-group"><label data-i18n="clients.client_type"></label>
                    <select name="client_type" class="form-control">${typeOptions}</select></div>
                <div class="form-group"><label data-i18n="clients.responsible"></label>
                    <select name="responsible_employee" class="form-control">
                        <option value="" data-i18n="common.select"></option>
                        ${userOptions}
                    </select></div>
                <button type="submit" class="btn btn-primary btn-block" data-i18n="common.save"></button>
            </form>
        `);

        modal.querySelector('#client-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target));
            // Пустая строка для FK — 400 у DRF. На создании поле просто не шлём,
            // на правке — null, чтобы ответственного можно было снять.
            if (!data.responsible_employee) {
                if (c) data.responsible_employee = null;
                else delete data.responsible_employee;
            }
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
