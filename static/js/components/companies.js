/**
 * Управление бизнесами (экран платформенного супер-администратора).
 *
 * Супер-админ видит платформенную сводку (статистика, фильтры, поиск),
 * список всех компаний с состоянием подписки и управляет подписками:
 * активация, продление, установка срока, заморозка/разморозка, история.
 *
 * Бизнес-данные компаний ему НЕ показываются (серверная изоляция):
 * здесь только операционные счётчики (сотрудники/клиенты/заказы) и
 * состояние подписки — управление платформой, а не чужая бухгалтерия.
 * Подписку нельзя менять никому, кроме супер-админа (backend-проверки).
 */
class CompaniesComponent {
    async render(container) {
        document.getElementById('page-title').setAttribute('data-i18n', 'companies.title');
        window.i18n.applyTranslations();

        this.container = container;
        this.page = 1;
        this.filters = { status: '', search: '' };
        this.companies = [];
        this.totalCount = 0;

        container.innerHTML = `
            <button class="btn btn-primary btn-block" id="add-company-btn" style="margin-bottom:12px;" data-i18n="companies.add"></button>

            <div id="companies-stats" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin-bottom:14px;"></div>

            <div class="form-group" style="margin-bottom:8px;">
                <input type="search" id="companies-search" class="form-control"
                    data-i18n-attr="placeholder" data-i18n="companies.search" autocomplete="off">
            </div>
            <div id="companies-filters" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px;">
                ${['', 'active', 'trial', 'grace', 'frozen', 'expired', 'expiring_soon'].map((s) => `
                    <button type="button" class="btn btn-sm ${this.filters.status === s ? 'btn-primary' : 'btn-secondary'}"
                        data-status="${s}" data-i18n="companies.${s ? s : 'all'}"></button>`).join('')}
            </div>

            <div class="table-scroll">
                <table class="data-table">
                    <thead><tr>
                        <th data-i18n="companies.name"></th>
                        <th data-i18n="companies.owner"></th>
                        <th data-i18n="companies.employees"></th>
                        <th data-i18n="companies.clients"></th>
                        <th data-i18n="companies.orders"></th>
                        <th data-i18n="companies.subscription"></th>
                        <th data-i18n="companies.plan"></th>
                        <th data-i18n="companies.subscription_end"></th>
                        <th data-i18n="companies.last_activity"></th>
                    </tr></thead>
                    <tbody id="companies-tbody"></tbody>
                </table>
            </div>
            <div class="pagination" id="companies-pagination" style="display:none;"></div>

            <div class="section-title" data-i18n="settings.language"></div>
            <div class="list-group">
                <div class="list-row lang-option" data-lang="uz_cyrl">
                    <span>Ўзбекча</span>
                    <span class="text-success font-bold" style="${window.i18n.currentLang === 'uz_cyrl' ? '' : 'visibility:hidden;'}">✓</span>
                </div>
                <div class="list-row lang-option" data-lang="ru">
                    <span>Русский</span>
                    <span class="text-success font-bold" style="${window.i18n.currentLang === 'ru' ? '' : 'visibility:hidden;'}">✓</span>
                </div>
                <div class="list-row lang-option" data-lang="ky">
                    <span>Кыргызча</span>
                    <span class="text-success font-bold" style="${window.i18n.currentLang === 'ky' ? '' : 'visibility:hidden;'}">✓</span>
                </div>
            </div>
            <div class="list-group" style="margin-top:16px;">
                <div class="list-row" id="logout-row">
                    <span class="text-danger">🚪 <span data-i18n="auth.logout"></span></span>
                </div>
            </div>
        `;

        container.querySelector('#add-company-btn').addEventListener('click', () => this.openForm());
        container.querySelectorAll('.lang-option').forEach((el) => {
            el.addEventListener('click', async () => {
                if (el.dataset.lang === window.i18n.currentLang) return;
                await window.i18n.setLanguage(el.dataset.lang);
                window.location.reload();
            });
        });
        container.querySelector('#logout-row').addEventListener('click', async () => {
            if (await window.confirmation.confirm(window.ui.t('auth.logout_confirm'), window.ui.t('auth.logout'))) {
                window.api.logout();
            }
        });
        container.querySelector('#companies-filters').addEventListener('click', (e) => {
            const btn = e.target.closest('[data-status]');
            if (!btn) return;
            this.filters.status = btn.dataset.status;
            this.page = 1;
            this.loadCompanies();
        });
        container.querySelector('#companies-search').addEventListener('input',
            window.ui.debounce((e) => {
                this.filters.search = e.target.value.trim();
                this.page = 1;
                this.loadCompanies();
            }, 300));

        window.i18n.applyTranslations();
        this.loadStats();
        await this.loadCompanies();
    }

    /** Платформенная сводка: всего / активных / замороженных / истёкших / истекают. */
    async loadStats() {
        const statsEl = this.container.querySelector('#companies-stats');
        try {
            const stats = await window.api.request('/companies/stats/');
            const cards = [
                { key: 'stat_total', value: stats.total, cls: 'blue' },
                { key: 'stat_active', value: stats.active, cls: 'green' },
                { key: 'stat_trial', value: stats.trial, cls: 'teal' },
                { key: 'stat_grace', value: stats.grace, cls: 'orange' },
                { key: 'stat_expiring', value: stats.expiring_soon, cls: 'purple' },
                { key: 'stat_expired', value: stats.expired, cls: 'red' },
                { key: 'stat_recent_subs', value: stats.recent_subscriptions, cls: 'blue' },
                { key: 'stat_recent_renewals', value: stats.recent_renewals, cls: 'green' },
            ];
            statsEl.innerHTML = cards.map((c) => `
                <div class="stat-card" style="padding:10px 12px;">
                    <div class="stat-title" data-i18n="companies.${c.key}"></div>
                    <div class="stat-value" style="font-size:20px;">${c.value}</div>
                </div>`).join('');
            window.i18n.applyTranslations();
        } catch (e) {
            statsEl.innerHTML = '';
        }
    }

    /** Бейдж состояния подписки. */
    subscriptionBadge(status, extra = '') {
        const map = {
            active: 'badge-ready',
            grace: 'badge-progress',
            expired: 'badge-cancel',
            frozen: 'badge-progress',
            cancelled: 'badge-cancel',
        };
        const cls = map[status] || 'badge-new';
        return `<span class="badge ${cls}" data-i18n="companies.status_${status}"></span>${extra}`;
    }

    /** Бейдж «Пробный период» для триалов. */
    trialBadge(isTrial) {
        return isTrial ? `<span class="badge badge-new" data-i18n="companies.trial_badge"></span>` : '';
    }

    /** Дней до окончания подписки (для активных). */
    daysLeft(end) {
        if (!end) return null;
        const ms = new Date(end).getTime() - Date.now();
        return Math.ceil(ms / 86400000);
    }

    async loadCompanies() {
        const tbody = this.container.querySelector('#companies-tbody');
        const params = new URLSearchParams({ page: this.page });
        if (this.filters.status) params.set('status', this.filters.status);
        if (this.filters.search) params.set('search', this.filters.search);

        window.listStates.tableLoading(tbody, 8, window.ui.t('common.loading'));
        try {
            const response = await window.api.request(`/companies/?${params}`);
            this.companies = response.results || [];
            this.totalCount = response.count ?? this.companies.length;

            if (!this.companies.length) {
                window.listStates.tableEmpty(tbody, 8, window.ui.t('common.no_data'));
                this.renderPagination(response);
                return;
            }

            tbody.innerHTML = this.companies.map((c) => `
                <tr class="company-row" data-id="${c.id}" tabindex="0" role="button"
                    aria-label="${window.ui.escape(c.name)}">
                    <td>
                        <div style="display:flex;align-items:center;gap:8px;">
                            ${c.logo_url ? `<img src="${window.ui.escape(c.logo_url)}" alt="" style="width:28px;height:28px;border-radius:6px;object-fit:cover;">` : ''}
                            <div>
                                <div style="font-weight:600;font-size:13px;">
                                    ${window.ui.escape(c.name)}
                                    ${c.is_active ? '' : `<span class="badge badge-cancel" data-i18n="settings.blocked"></span>`}
                                </div>
                                ${this.trialBadge(c.is_trial)}
                                ${this.subscriptionBadge(c.subscription_status)}
                                ${c.has_renewal_request ? `<span class="badge badge-progress" data-i18n="companies.renewal_request_badge"></span>` : ''}
                            </div>
                        </div>
                    </td>
                    <td style="white-space:nowrap;">${window.ui.escape(c.owner_full_name || c.owner_username || '-')}</td>
                    <td>${c.users_count}</td>
                    <td>${c.clients_count}</td>
                    <td>${c.orders_count}</td>
                    <td style="white-space:nowrap;">${window.ui.escape(c.plan_name || '-')}</td>
                    <td style="white-space:nowrap;">
                        ${c.subscription_end ? window.ui.date(c.subscription_end) : '-'}
                        ${(c.subscription_status === 'active' && c.subscription_end) ? `<div class="text-sm text-muted">${this.daysLeft(c.subscription_end)} ${window.ui.t('companies.days_left')}</div>` : ''}
                    </td>
                    <td style="white-space:nowrap;font-size:11px;">${window.ui.datetime(c.subscription_end)}</td>
                    <td style="white-space:nowrap;font-size:11px;color:var(--text-muted);">${window.ui.datetime(c.last_activity)}</td>
                </tr>`).join('');

            tbody.querySelectorAll('.company-row').forEach((row) => {
                row.addEventListener('click', () => {
                    const company = this.companies.find((c) => c.id === Number(row.dataset.id));
                    this.openDetail(company);
                });
                row.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        row.click();
                    }
                });
            });
            this.renderPagination(response);
            window.i18n.applyTranslations();
        } catch (e) {
            window.listStates.tableError(tbody, 8, window.ui.t('common.error_loading'), () => this.loadCompanies());
        }
    }

    async openDetail(c) {
        const modal = window.ui.modal('companies.title', `
            <div class="card-title">
                <span>${window.ui.escape(c.name)}</span>
                <span>
                    ${this.subscriptionBadge(c.subscription_status)}
                    ${c.is_active ? '' : `<span class="badge badge-cancel" data-i18n="settings.blocked"></span>`}
                </span>
            </div>

            ${c.has_renewal_request ? `
                <div class="alert-box" style="margin-bottom:14px;">
                    <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;">
                        <span style="display:inline-flex;align-items:center;gap:6px;">🔄 <span data-i18n="companies.renewal_request_text"></span></span>
                        <button class="btn btn-primary btn-sm" id="sub-handle-request" style="width:auto;"
                                data-i18n="companies.extend_30"></button>
                    </div>
                </div>` : ''}

            <div class="section-title" data-i18n="companies.owner"></div>
            <div class="list-group" style="box-shadow:none;border:1px solid var(--border);margin-bottom:14px;">
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm text-muted" data-i18n="companies.owner"></span>
                    <span class="text-sm font-bold">${window.ui.escape(c.owner_full_name || c.owner_username || '-')}</span>
                </div>
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm text-muted" data-i18n="companies.employees"></span>
                    <span class="text-sm font-bold">${c.users_count}</span>
                </div>
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm text-muted" data-i18n="companies.clients"></span>
                    <span class="text-sm font-bold">${c.clients_count}</span>
                </div>
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm text-muted" data-i18n="companies.orders"></span>
                    <span class="text-sm font-bold">${c.orders_count}</span>
                </div>
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm text-muted" data-i18n="companies.created"></span>
                    <span class="text-sm font-bold">${window.ui.date(c.created_at)}</span>
                </div>
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm text-muted" data-i18n="companies.last_activity"></span>
                    <span class="text-sm font-bold">${window.ui.datetime(c.last_activity)}</span>
                </div>
            </div>

            <div class="section-title" data-i18n="companies.subscription"></div>
            <div class="list-group" style="box-shadow:none;border:1px solid var(--border);margin-bottom:14px;">
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm text-muted" data-i18n="companies.plan"></span>
                    <span class="text-sm font-bold">${window.ui.escape(c.plan_name || '-')} ${this.trialBadge(c.is_trial)}</span>
                </div>
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm text-muted" data-i18n="companies.subscription_start"></span>
                    <span class="text-sm font-bold">${window.ui.datetime(c.subscription_start)}</span>
                </div>
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm text-muted" data-i18n="companies.subscription_end"></span>
                    <span class="text-sm font-bold">${window.ui.datetime(c.subscription_end)}</span>
                </div>
                ${c.days_left !== null && c.days_left !== undefined && c.subscription_status === 'active' ? `
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm text-muted" data-i18n="subscription.days_left_label"></span>
                    <span class="text-sm font-bold">${c.days_left} ${window.ui.t('companies.days_left')}</span>
                </div>` : ''}
            </div>

            <div class="section-title" data-i18n="companies.actions"></div>
            <div style="display:flex;flex-direction:column;gap:8px;margin-bottom:14px;">
                <button class="btn btn-primary btn-block" id="sub-activate" data-i18n="companies.activate"></button>
                <button class="btn btn-secondary btn-block" id="sub-extend-30" data-i18n="companies.extend_30"></button>
                <button class="btn btn-secondary btn-block" id="sub-extend-custom" data-i18n="companies.extend_custom"></button>
                <button class="btn btn-secondary btn-block" id="sub-set-end" data-i18n="companies.set_end"></button>
                <button class="btn btn-secondary btn-block" id="sub-change-plan" data-i18n="companies.plan_change"></button>
                <button class="btn ${c.subscription_status === 'frozen' ? 'btn-success' : 'btn-danger'} btn-block" id="sub-freeze"
                    data-i18n="${c.subscription_status === 'frozen' ? 'companies.unfreeze' : 'companies.freeze'}"></button>
                <button class="btn ${c.is_active ? 'btn-danger' : 'btn-success'} btn-block" id="toggle-company"
                    data-i18n="${c.is_active ? 'companies.block' : 'companies.unblock'}"></button>
            </div>

            <div class="section-title" data-i18n="companies.history"></div>
            <div id="sub-history" style="margin-bottom:8px;">
                <div class="list-state list-state-loading"><span class="spinner"></span></div>
            </div>
            <div class="section-title" data-i18n="subscription.title"></div>
            <div id="sub-panel"><div class="list-state list-state-loading"><span class="spinner"></span></div></div>
            <button class="btn ${c.is_active ? 'btn-danger' : 'btn-success'} btn-block" id="toggle-company"
                data-i18n="${c.is_active ? 'companies.block' : 'companies.unblock'}"></button>
        `);
        window.i18n.applyTranslations();
        modal.querySelector('#toggle-company').addEventListener('click', async () => {
            try {
                await window.api.request(`/companies/${c.id}/toggle_active/`, { method: 'POST' });
                window.ui.closeModal(modal);
                window.toast.success(window.ui.t('common.success'));
                this.loadCompanies();
                this.loadStats();
            } catch (error) {
                window.toast.error(window.ui.errorText(error));
            }
        });

        try {
            const detail = await window.api.request(`/billing/subscriptions/${c.id}/`);
            if (modal.isConnected) this.renderSubscription(modal, detail);
        } catch (e) {
            const panel = modal.querySelector('#sub-panel');
            if (panel) {
                panel.innerHTML = `<div class="list-state list-state-empty" data-i18n="subscription.none"></div>`;
                window.i18n.applyTranslations();
            }
        }
        this.loadHistory(c.id, modal);
        window.i18n.applyTranslations();
    }

    async loadHistory(companyId, modal) {
        const historyEl = modal.querySelector('#sub-history');
        try {
            const history = await window.api.request(`/companies/${companyId}/subscription_history/`);
            if (!history || !history.length) {
                historyEl.innerHTML = `<div class="list-state list-state-empty" data-i18n="companies.no_history"></div>`;
            } else {
                const actionLabels = {
                    activated: 'companies.activate', extended: 'companies.extend_30',
                    end_set: 'companies.set_end', grace_started: 'subscription.grace_title',
                    frozen: 'companies.freeze', unfrozen: 'companies.unfreeze',
                    expired: 'companies.subscription_expired',
                    plan_changed: 'companies.plan_change',
                    cancelled: 'companies.status_cancelled',
                };
                historyEl.innerHTML = `<div class="list-group" style="box-shadow:none;border:1px solid var(--border);">` +
                    history.map((h) => `
                        <div class="list-row" style="cursor:default;font-size:12px;">
                            <div>
                                <div style="font-weight:600;" data-i18n="${actionLabels[h.action] || 'common.details'}"></div>
                                <div class="text-sm text-muted">
                                    ${window.ui.escape(h.actor)} · ${window.ui.datetime(h.created_at)}
                                    ${h.days_added ? ` · +${h.days_added} ${window.ui.t('companies.days_left')}` : ''}
                                    ${h.old_plan || h.new_plan ? ` · ${window.ui.escape(h.old_plan || '—')} → ${window.ui.escape(h.new_plan || '—')}` : ''}
                                </div>
                            </div>
                            <div class="text-sm" style="white-space:nowrap;color:var(--text-muted);">
                                ${h.old_status || '—'} → ${h.new_status || '—'}
                            </div>
                        </div>`).join('') + `</div>`;
            }
            window.i18n.applyTranslations();
        } catch (e) {
            historyEl.innerHTML = `<div class="list-state list-state-error">${window.ui.t('common.error')}</div>`;
        }
    }

    /** Продление на произвольное количество дней (с подтверждением числа). */
    openExtendModal(c, parentModal) {
        const modal = window.ui.modal('companies.extend_custom', `
            <form id="extend-form">
                <div class="form-group">
                    <label data-i18n="companies.extend_custom_label"></label>
                    <input name="days" type="number" class="form-control" min="1" max="3650" required autofocus>
                    <p class="text-sm text-muted" style="margin-top:4px;" data-i18n="companies.extend_prompt"></p>
                </div>
                <button type="submit" class="btn btn-primary btn-block" data-i18n="common.save"></button>
            </form>
        `);
        modal.querySelector('#extend-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const days = Number(new FormData(e.target).get('days'));
            if (!days || days < 1) {
                window.toast.error(window.ui.t('companies.extend_prompt'));
                return;
            }
            await this.runAction(`/companies/${c.id}/subscription_extend/`, { days }, parentModal, c);
            window.ui.closeModal(modal);
        });
    }

    /** Смена тарифа: список активных планов + подтверждение. */
    async openPlanModal(c, parentModal) {
        let plans;
        try {
            plans = await window.api.request('/companies/plans/');
        } catch (e) {
            window.toast.error(window.ui.errorText(e));
            return;
        }
        const modal = window.ui.modal('companies.plan_change', `
            <div class="form-group">
                <label data-i18n="companies.plan_change_select"></label>
                ${plans.map((p) => `
                    <label class="list-row" style="cursor:pointer;border:1px solid var(--border);border-radius:8px;margin-bottom:6px;padding:10px 12px;">
                        <input type="radio" name="plan" value="${p.id}" ${p.id === c.plan_id ? 'checked' : ''} style="margin-right:10px;">
                        <span style="flex:1;">
                            <span style="font-weight:600;">${window.ui.escape(p.name)}</span>
                            <span class="text-sm text-muted" style="display:block;">${window.ui.escape(p.description || '')} · ${p.duration_days} ${window.ui.t('companies.days_left')}</span>
                        </span>
                    </label>`).join('')}
            </div>
            <button class="btn btn-primary btn-block" id="plan-change-submit" data-i18n="common.save"></button>
        `);
        modal.querySelector('#plan-change-submit').addEventListener('click', async () => {
            const selected = modal.querySelector('input[name=plan]:checked');
            if (!selected) {
                window.toast.error(window.ui.t('companies.plan_change_select'));
                return;
            }
            const planId = Number(selected.value);
            if (planId === c.plan_id) {
                window.ui.closeModal(modal);
                return;
            }
            const ok = await window.confirmation.confirm(
                window.ui.t('companies.plan_change_confirm'), window.ui.t('companies.plan_change'));
            if (!ok) return;
            await this.runAction(`/companies/${c.id}/subscription_change_plan/`, { plan_id: planId }, parentModal, c);
            window.ui.closeModal(modal);
        });
    }

    /** Установка точной даты окончания. */
    openSetEndModal(c, parentModal) {
        const modal = window.ui.modal('companies.set_end', `
            <form id="set-end-form">
                <div class="form-group">
                    <label data-i18n="companies.set_end_prompt"></label>
                    <input name="end" type="datetime-local" class="form-control" required autofocus>
                </div>
                <button type="submit" class="btn btn-primary btn-block" data-i18n="common.save"></button>
            </form>
        `);
        modal.querySelector('#set-end-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const local = new FormData(e.target).get('end');
            if (!local) return;
            const end = new Date(local).toISOString();
            await this.runAction(`/companies/${c.id}/subscription_set_end/`, { end }, parentModal, c);
            window.ui.closeModal(modal);
        });
    }

    /** Общий запуск действия над подпиской: POST → тост → обновление списка и статистики. */
    async runAction(endpoint, payload, modal, c) {
        try {
            await window.api.request(endpoint, { method: 'POST', body: JSON.stringify(payload) });
            window.toast.success(window.ui.t('common.success'));
            window.ui.closeModal(modal);
            this.loadCompanies();
            this.loadStats();
        } catch (error) {
            window.toast.error(window.ui.errorText(error));
        }
    }

    /** Панель подписки в карточке компании: статус, срок, действия, счета. */
    renderSubscription(modal, data) {
        const panel = modal.querySelector('#sub-panel');
        if (!panel) return;
        const t = (k, p) => window.ui.t(k, p);
        const blocked = data.is_blocked;
        const statusBadge = blocked
            ? '<span class="badge badge-cancel" data-i18n="subscription.frozen"></span>'
            : '<span class="badge badge-ready" data-i18n="subscription.active"></span>';

        const pendingInvoices = (data.invoices || []).filter((i) => i.status === 'pending');
        const actions = [];
        if (blocked) {
            actions.push(`<button class="btn btn-success btn-sm btn-block" data-sub-action="activate">${t('subscription.activate', { days: 30 })}</button>`);
            actions.push(`<button class="btn btn-secondary btn-sm btn-block" data-sub-action="unfreeze">${t('subscription.unfreeze')}</button>`);
        } else {
            actions.push(`<button class="btn btn-secondary btn-sm btn-block" data-sub-action="extend">${t('subscription.extend', { days: 30 })}</button>`);
            actions.push(`<button class="btn btn-danger btn-sm btn-block" data-sub-action="freeze">${t('subscription.freeze')}</button>`);
        }

        panel.innerHTML = `
            <div class="list-group" style="box-shadow:none;border:1px solid var(--border-color);margin-bottom:10px;">
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm text-muted" data-i18n="subscription.plan"></span>
                    <span class="text-sm font-bold">${window.ui.escape(data.plan)} ${statusBadge}</span>
                </div>
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm text-muted" data-i18n="subscription.expires"></span>
                    <span class="text-sm font-bold">${window.ui.escape((data.expires_at || '').slice(0, 10)) || '—'}</span>
                </div>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px;">${actions.join('')}</div>
            ${pendingInvoices.length ? `
                <div class="section-title" data-i18n="subscription.invoices"></div>
                <div class="list-group" style="box-shadow:none;border:1px solid var(--border-color);margin-bottom:10px;">
                    ${pendingInvoices.map((i) => `
                        <div class="list-row" style="cursor:pointer;" data-confirm-invoice="${i.id}">
                            <span class="text-sm">#${i.id} · ${i.amount} ${i.currency} <span class="badge badge-progress" data-i18n="subscription.pending"></span></span>
                            <span class="text-sm font-bold" style="color:var(--primary);" data-i18n="subscription.confirm_payment"></span>
                        </div>`).join('')}
                </div>` : ''}
        `;
        window.i18n.applyTranslations();

        panel.querySelectorAll('[data-sub-action]').forEach((btn) => {
            btn.addEventListener('click', async () => {
                const action = btn.dataset.subAction;
                const body = action === 'extend' ? { days: 30 } : {};
                try {
                    await window.api.request(`/billing/subscriptions/${data.id}/${action}/`, {
                        method: 'POST', body: JSON.stringify(body),
                    });
                    window.toast.success(window.ui.t('common.success'));
                    window.ui.closeModal(modal);
                    await this.load();
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        });
        panel.querySelectorAll('[data-confirm-invoice]').forEach((row) => {
            row.addEventListener('click', async () => {
                try {
                    await window.api.request(`/billing/subscriptions/${data.id}/confirm_payment/`, {
                        method: 'POST', body: JSON.stringify({ invoice_id: Number(row.dataset.confirmInvoice) }),
                    });
                    window.toast.success(window.ui.t('common.success'));
                    window.ui.closeModal(modal);
                    await this.load();
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        });
    }

    openForm() {
        const modal = window.ui.modal('companies.add', `
            <form id="company-form">
                <div class="form-group"><label data-i18n="companies.name"></label>
                    <input name="name" class="form-control" required></div>
                <div class="section-title" data-i18n="companies.owner_account"></div>
                <div class="form-group"><label data-i18n="setup.full_name"></label>
                    <input name="owner_full_name" class="form-control"></div>
                <div class="form-group"><label data-i18n="setup.phone"></label>
                    <input name="owner_phone" class="form-control"></div>
                <div class="form-group"><label data-i18n="auth.username"></label>
                    <input name="owner_username" class="form-control" required minlength="3"></div>
                <div class="form-group"><label data-i18n="auth.password"></label>
                    <input name="owner_password" type="password" class="form-control" required minlength="8"></div>
                <button type="submit" class="btn btn-primary btn-block" data-i18n="common.save"></button>
            </form>
        `);
        modal.querySelector('#company-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target));
            await window.ui.submitGuard(e.target.querySelector('button[type=submit]'), async () => {
                try {
                    await window.api.request('/companies/', { method: 'POST', body: JSON.stringify(data) });
                    window.ui.closeModal(modal);
                    window.toast.success(window.ui.t('common.success'));
                    this.loadCompanies();
                    this.loadStats();
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        });
    }
}

window.CompaniesComponent = new CompaniesComponent();
