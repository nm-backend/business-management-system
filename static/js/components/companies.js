/**
 * Компании (экран платформенного супер-администратора).
 *
 * Супер-админ создаёт компании вместе с их владельцами, блокирует/разблокирует.
 * Бизнес-данные компаний ему недоступны (серверная изоляция).
 */
class CompaniesComponent {
    async render(container) {
        document.getElementById('page-title').setAttribute('data-i18n', 'companies.title');
        window.i18n.applyTranslations();

        container.innerHTML = `
            <button class="btn btn-primary btn-block" id="add-company-btn" style="margin-bottom:12px;" data-i18n="companies.add"></button>
            <div id="companies-list"></div>
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

        window.i18n.applyTranslations();
        await this.load();
    }

    async load() {
        const listEl = document.getElementById('companies-list');
        // Пользователь мог уйти со страницы, пока шёл запрос: контейнера
        // больше нет, рисовать некуда.
        if (window.listStates.gone(listEl)) return;
        window.listStates.loading(listEl, window.ui.t('common.loading'));
        try {
            const response = await window.api.request('/companies/');
            this.companies = response.results || response;
            if (!this.companies.length) {
                window.listStates.empty(listEl, window.ui.t('common.no_data'));
                return;
            }
            listEl.innerHTML = `<div class="list-group">${this.companies.map((c) => `
                <div class="list-row" data-id="${c.id}">
                    <div>
                        <div style="font-weight:600;font-size:14px;">
                            ${window.ui.escape(c.name)}
                            ${c.is_active ? '' : `<span class="badge badge-cancel" data-i18n="settings.blocked"></span>`}
                        </div>
                        <div class="text-sm text-muted">
                            ${window.ui.escape(c.owner_full_name || c.owner_username || '-')} ·
                            <span data-i18n="companies.users"></span>: ${c.users_count}
                        </div>
                    </div>
                    <span>›</span>
                </div>`).join('')}</div>`;
            listEl.querySelectorAll('[data-id]').forEach((row) => {
                row.addEventListener('click', () => {
                    const company = this.companies.find((c) => c.id === Number(row.dataset.id));
                    this.openDetail(company);
                });
            });
            window.i18n.applyTranslations();
        } catch (e) {
            window.listStates.error(listEl, window.ui.t('common.error'), () => this.load());
        }
    }

    async openDetail(c) {
        const modal = window.ui.modal('companies.title', `
            <div class="card-title">
                <span>${window.ui.escape(c.name)}</span>
                <span class="badge ${c.is_active ? 'badge-ready' : 'badge-cancel'}"
                    data-i18n="${c.is_active ? 'common.active' : 'settings.blocked'}"></span>
            </div>
            <div class="list-group" style="box-shadow:none;border:1px solid var(--border);margin-bottom:14px;">
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm text-muted" data-i18n="companies.owner"></span>
                    <span class="text-sm font-bold">${window.ui.escape(c.owner_full_name || c.owner_username || '-')}</span>
                </div>
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm text-muted" data-i18n="companies.users"></span>
                    <span class="text-sm font-bold">${c.users_count}</span>
                </div>
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
                await this.load();
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
                    await this.load();
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        });
    }
}

window.CompaniesComponent = new CompaniesComponent();
