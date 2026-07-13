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

    openDetail(c) {
        const modal = window.ui.modal('companies.title', `
            <div class="card-title">
                <span>${window.ui.escape(c.name)}</span>
                <span class="badge ${c.is_active ? 'badge-ready' : 'badge-cancel'}"
                    data-i18n="${c.is_active ? 'common.active' : 'settings.blocked'}"></span>
            </div>
            <div class="list-group" style="box-shadow:none;border:1px solid #efeff4;margin-bottom:14px;">
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm text-muted" data-i18n="companies.owner"></span>
                    <span class="text-sm font-bold">${window.ui.escape(c.owner_full_name || c.owner_username || '-')}</span>
                </div>
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm text-muted" data-i18n="companies.users"></span>
                    <span class="text-sm font-bold">${c.users_count}</span>
                </div>
            </div>
            <button class="btn ${c.is_active ? 'btn-danger' : 'btn-success'} btn-block" id="toggle-company"
                data-i18n="${c.is_active ? 'companies.block' : 'companies.unblock'}"></button>
        `);
        modal.querySelector('#toggle-company').addEventListener('click', async () => {
            try {
                await window.api.request(`/companies/${c.id}/toggle_active/`, { method: 'POST' });
                modal.remove();
                window.toast.success(window.ui.t('common.success'));
                await this.load();
            } catch (error) {
                window.toast.error(window.ui.errorText(error));
            }
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
                    modal.remove();
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
