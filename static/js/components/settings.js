/**
 * "Кўпроқ" (настройки): профиль, язык, смена пароля,
 * управление аккаунтами (owner), экспорт отчётов, выход.
 */
class SettingsComponent {
    async render(container) {
        document.getElementById('page-title').setAttribute('data-i18n', 'settings.title');
        this.container = container;
        const user = window.currentUser;
        const currentLang = window.i18n.currentLang;

        // Статус push-уведомлений
        const notifStatus = 'Notification' in window ? Notification.permission : 'unsupported';
        const notifLabel = notifStatus === 'granted' ? window.ui.t('common.enabled')
            : notifStatus === 'denied' ? window.ui.t('common.disabled')
            : window.ui.t('settings.enable');

        container.innerHTML = `
            <div class="card" style="display:flex;align-items:center;gap:12px;">
                <div class="thumb" style="width:52px;height:52px;border-radius:50%;">👤</div>
                <div>
                    <div style="font-weight:600;font-size:16px;">${window.ui.escape(user.full_name || user.username)}</div>
                    <div class="text-sm text-muted" data-i18n="roles.${user.role}"></div>
                </div>
            </div>

            <div class="section-title" data-i18n="nav.menu"></div>
            <div class="list-group">
                <a class="list-row" href="#/messages" style="text-decoration:none;color:inherit;">
                    <span>✉️ <span data-i18n="messages_section.title"></span></span><span>›</span>
                </a>
                ${!user.is_worker ? `
                    <a class="list-row" href="#/finished-products" style="text-decoration:none;color:inherit;">
                        <span>🪟 <span data-i18n="warehouse.finished_title"></span></span><span>›</span>
                    </a>
                    <a class="list-row" href="#/production" style="text-decoration:none;color:inherit;">
                        <span>🛠️ <span data-i18n="production.title"></span></span><span>›</span>
                    </a>` : ''}
                ${user.is_owner ? `
                    <a class="list-row" href="#/finance" style="text-decoration:none;color:inherit;">
                        <span>💰 <span data-i18n="finance.title"></span></span><span>›</span>
                    </a>` : ''}
            </div>

            <div class="section-title" data-i18n="settings.language"></div>
            <div class="list-group">
                <div class="list-row lang-option" data-lang="uz_cyrl">
                    <span>Ўзбекча</span>
                    <span class="text-success font-bold" style="${currentLang === 'uz_cyrl' ? '' : 'visibility:hidden;'}">✓</span>
                </div>
                <div class="list-row lang-option" data-lang="ru">
                    <span>Русский</span>
                    <span class="text-success font-bold" style="${currentLang === 'ru' ? '' : 'visibility:hidden;'}">✓</span>
                </div>
                <div class="list-row lang-option" data-lang="ky">
                    <span>Кыргызча</span>
                    <span class="text-success font-bold" style="${currentLang === 'ky' ? '' : 'visibility:hidden;'}">✓</span>
                </div>
            </div>

            <div class="section-title" data-i18n="settings.appearance"></div>
            <div class="list-group">
                <div class="list-row" style="cursor:pointer;">
                    <span>🌙 <span data-i18n="settings.dark_mode"></span></span>
                    <label class="toggle-switch">
                        <input type="checkbox" id="dark-mode-toggle" ${document.body.classList.contains('theme-dark') ? 'checked' : ''}>
                        <span class="toggle-slider"></span>
                    </label>
                </div>
            </div>

            <div class="section-title" data-i18n="settings.notifications"></div>
            <div class="list-group">
                <div class="list-row" id="notif-permission-row" style="cursor:pointer;">
                    <span>🔔 <span data-i18n="settings.push_notifications"></span></span>
                    <span class="badge ${notifStatus === 'granted' ? 'badge-ready' : notifStatus === 'denied' ? 'badge-cancel' : 'badge-progress'}" id="notif-status-badge">${notifLabel}</span>
                </div>
            </div>

            ${user.is_owner ? `
                <div class="section-title" data-i18n="nav.accounts"></div>
                <div class="list-group" id="users-list">
                    <div class="list-state list-state-loading"><span class="spinner"></span></div>
                </div>
                <button class="btn btn-primary btn-block" id="add-user-btn" style="margin-bottom:16px;" data-i18n="settings.add_account"></button>` : ''}

            ${user.is_owner || user.is_admin ? `
                <div class="section-title" data-i18n="settings.export"></div>
                <div class="list-group">
                    <div class="list-row" data-export="/reports/export/stock/" data-file="stock-report.xlsx">
                        <span>📦 <span data-i18n="export.stock"></span></span><span>Excel</span>
                    </div>
                    <div class="list-row" data-export="/reports/export/orders/" data-file="orders-report.xlsx">
                        <span>📋 <span data-i18n="export.orders"></span></span><span>Excel</span>
                    </div>
                    <div class="list-row" data-export="/reports/export/work/" data-file="work-report.xlsx">
                        <span>🛠️ <span data-i18n="export.work"></span></span><span>Excel</span>
                    </div>
                    ${user.is_owner ? `
                        <div class="list-row" data-export="/reports/export/finance/" data-file="finance-report.xlsx">
                            <span>💰 <span data-i18n="export.finance"></span></span><span>Excel</span>
                        </div>` : ''}
                </div>` : ''}

            <div class="section-title" data-i18n="settings.security"></div>
            <div class="list-group">
                <div class="list-row" id="change-password-row">
                    <span>🔑 <span data-i18n="auth.change_password"></span></span><span>›</span>
                </div>
                <div class="list-row" id="about-row">
                    <span>ℹ️ <span data-i18n="about.title"></span></span><span>›</span>
                </div>
                <div class="list-row" id="logout-row">
                    <span class="text-danger">🚪 <span data-i18n="auth.logout"></span></span>
                </div>
            </div>
        `;

        // Dark mode toggle
        const darkToggle = container.querySelector('#dark-mode-toggle');
        if (darkToggle) {
            darkToggle.addEventListener('change', () => {
                if (darkToggle.checked) {
                    document.body.classList.add('theme-dark');
                    localStorage.setItem('theme', 'dark');
                } else {
                    document.body.classList.remove('theme-dark');
                    localStorage.setItem('theme', 'light');
                }
            });
        }

        // Push notifications permission
        const notifRow = container.querySelector('#notif-permission-row');
        if (notifRow) {
            notifRow.addEventListener('click', async () => {
                const result = await window.requestNotificationPermission();
                const badge = container.querySelector('#notif-status-badge');
                if (result === 'granted') {
                    badge.textContent = window.ui.t('common.enabled');
                    badge.className = 'badge badge-ready';
                    window.toast.success('🔔 ' + window.ui.t('settings.notifications_on'));
                } else if (result === 'denied') {
                    badge.textContent = window.ui.t('common.disabled');
                    badge.className = 'badge badge-cancel';
                    window.toast.info(window.ui.t('settings.notifications_blocked'));
                }
            });
        }

        container.querySelectorAll('.lang-option').forEach((el) => {
            el.addEventListener('click', () => this.changeLanguage(el.dataset.lang));
        });
        container.querySelector('#change-password-row').addEventListener('click', () => this.openChangePassword());
        container.querySelector('#about-row').addEventListener('click', () => this.openAbout());
        container.querySelector('#logout-row').addEventListener('click', async () => {
            if (await window.confirmation.confirm(window.ui.t('auth.logout_confirm'), window.ui.t('auth.logout'))) {
                window.api.logout();
            }
        });
        container.querySelectorAll('[data-export]').forEach((row) => {
            row.addEventListener('click', () => this.download(row.dataset.export, row.dataset.file));
        });

        if (user.is_owner) {
            container.querySelector('#add-user-btn').addEventListener('click', () => this.openUserForm());
            this.loadUsers();
        }
        window.i18n.applyTranslations();
    }

    async changeLanguage(lang) {
        if (lang === window.i18n.currentLang) return;
        await window.i18n.setLanguage(lang);
        window.location.reload();
    }

    async download(endpoint, filename) {
        try {
            const tokens = window.api.getTokens();
            const response = await fetch(`/api/v1${endpoint}`, {
                headers: { Authorization: `Bearer ${tokens.access}` },
            });
            if (!response.ok) throw new Error('Export failed');
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            a.click();
            URL.revokeObjectURL(url);
            window.toast.success(window.ui.t('export.report_ready'));
        } catch (e) {
            window.toast.error(window.ui.t('common.error'));
        }
    }

    /** «О приложении»: версия, разработчики, лицензия, контакты, инфо о системе. */
    openAbout() {
        const user = window.currentUser;
        const t = (k) => window.ui.t(k);
        const row = (labelKey, valueHtml) => `
            <div class="list-row" style="cursor:default;">
                <span class="text-sm text-muted" data-i18n="${labelKey}"></span>
                <span class="text-sm font-bold" style="text-align:right;">${valueHtml}</span>
            </div>`;
        const modal = window.ui.modal('about.title', `
            <div style="text-align:center;padding:6px 0 14px;">
                <div class="stat-icon blue" style="margin:0 auto 10px;width:52px;height:52px;font-size:26px;">🧊</div>
                <div style="font-weight:800;font-size:18px;">SkladPro.Nod</div>
                <div class="text-sm text-muted" data-i18n="app.tagline"></div>
            </div>
            <div class="section-title" data-i18n="about.system"></div>
            <div class="list-group" style="box-shadow:none;border:1px solid var(--border-color);">
                ${row('about.version', '1.0.0')}
                ${row('about.app_name', 'SkladPro.Nod')}
                ${user.company_name ? row('about.company_label', window.ui.escape(user.company_name)) : ''}
                ${row('roles.' + user.role, window.ui.escape(user.full_name || user.username))}
            </div>
            <div class="section-title" data-i18n="about.developers"></div>
            <div class="list-group" style="box-shadow:none;border:1px solid var(--border-color);">
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm font-bold">Nurullo Musajanov</span>
                    <span class="text-sm text-muted">Backend Developer</span>
                </div>
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm font-bold">Claude (Anthropic AI)</span>
                    <span class="text-sm text-muted" style="text-align:right;">Financial Architecture &amp; System Design</span>
                </div>
            </div>
            <div class="section-title" data-i18n="about.contacts"></div>
            <div class="list-group" style="box-shadow:none;border:1px solid var(--border-color);">
                ${row('about.license', 'MIT License')}
                <a class="list-row" href="https://github.com/nm-backend" target="_blank" rel="noopener noreferrer" style="text-decoration:none;color:inherit;">
                    <span class="text-sm text-muted">GitHub</span>
                    <span class="text-sm font-bold" style="color:var(--primary);">github.com/nm-backend ›</span>
                </a>
            </div>
        `);
        void modal;
    }

    async loadUsers() {
        const listEl = this.container.querySelector('#users-list');
        try {
            const response = await window.api.request('/accounts/users/');
            this.users = response.results || response;
            listEl.innerHTML = this.users.map((u) => `
                <div class="list-row" data-user="${u.id}">
                    <div>
                        <div style="font-weight:600;font-size:14px;">
                            ${window.ui.escape(u.full_name || u.username)}
                            ${u.is_active === false ? `<span class="badge badge-cancel" data-i18n="settings.blocked"></span>` : ''}
                        </div>
                        <div class="text-sm text-muted">${window.ui.escape(u.username)} · <span data-i18n="roles.${u.role}"></span></div>
                    </div>
                    <span>›</span>
                </div>`).join('');
            listEl.querySelectorAll('[data-user]').forEach((row) => {
                row.addEventListener('click', () => {
                    const target = this.users.find((u) => u.id === Number(row.dataset.user));
                    this.openUserDetail(target);
                });
            });
            window.i18n.applyTranslations();
        } catch (e) {
            window.listStates.error(listEl, window.ui.t('common.error'), () => this.loadUsers());
        }
    }

    openUserDetail(u) {
        if (u.role === 'owner') return; // владелец управляется только через профиль
        const modal = window.ui.modal('nav.accounts', `
            <div class="card-title">
                <span>${window.ui.escape(u.full_name || u.username)}</span>
                <span class="badge badge-new" data-i18n="roles.${u.role}"></span>
            </div>
            ${u.role === 'admin' || u.role === 'worker' ? `
                <div class="list-group" style="box-shadow:none;border:1px solid #efeff4;margin-bottom:14px;">
                    <label class="list-row" style="cursor:pointer;">
                        <span class="text-sm" data-i18n="settings.can_write_to_owner"></span>
                        <input type="checkbox" id="perm-write-owner" ${u.can_write_to_owner ? 'checked' : ''}>
                    </label>
                    ${u.role === 'admin' ? `
                        <label class="list-row" style="cursor:pointer;">
                            <span class="text-sm" data-i18n="settings.can_create_workers"></span>
                            <input type="checkbox" id="perm-create-workers" ${u.can_create_workers ? 'checked' : ''}>
                        </label>
                        <label class="list-row" style="cursor:pointer;">
                            <span class="text-sm" data-i18n="settings.can_see_other_workers"></span>
                            <input type="checkbox" id="perm-see-workers" ${u.can_see_other_workers ? 'checked' : ''}>
                        </label>` : ''}
                </div>` : ''}
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                <button class="btn ${u.is_active === false ? 'btn-success' : 'btn-danger'} btn-sm" id="toggle-active"
                    data-i18n="${u.is_active === false ? 'settings.unblock' : 'settings.block'}"></button>
                <button class="btn btn-secondary btn-sm" id="reset-password" data-i18n="settings.reset_password"></button>
            </div>
        `);

        const savePerm = async (field, value) => {
            try {
                await window.api.request(`/accounts/users/${u.id}/`, {
                    method: 'PATCH', body: JSON.stringify({ [field]: value }),
                });
                window.toast.success(window.ui.t('common.success'));
            } catch (error) {
                window.toast.error(window.ui.errorText(error));
            }
        };
        const bindPerm = (id, field) => {
            const box = modal.querySelector(`#${id}`);
            if (box) box.addEventListener('change', () => savePerm(field, box.checked));
        };
        bindPerm('perm-write-owner', 'can_write_to_owner');
        bindPerm('perm-create-workers', 'can_create_workers');
        bindPerm('perm-see-workers', 'can_see_other_workers');

        modal.querySelector('#toggle-active').addEventListener('click', async () => {
            try {
                await window.api.request(`/accounts/users/${u.id}/toggle_active/`, { method: 'POST' });
                modal.remove();
                window.toast.success(window.ui.t('common.success'));
                await this.loadUsers();
            } catch (error) {
                window.toast.error(window.ui.errorText(error));
            }
        });

        modal.querySelector('#reset-password').addEventListener('click', () => {
            modal.remove();
            this.openResetPassword(u);
        });
    }

    openResetPassword(u) {
        const modal = window.ui.modal('settings.reset_password', `
            <p style="margin-bottom:12px;font-weight:600;">${window.ui.escape(u.full_name || u.username)}</p>
            <form id="reset-form">
                <div class="form-group"><label data-i18n="auth.new_password"></label>
                    <input name="new_password" type="password" class="form-control" required minlength="8"></div>
                <button type="submit" class="btn btn-primary btn-block" data-i18n="common.save"></button>
            </form>
        `);
        modal.querySelector('#reset-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target));
            await window.ui.submitGuard(e.target.querySelector('button[type=submit]'), async () => {
                try {
                    await window.api.request(`/accounts/users/${u.id}/reset_password/`, {
                        method: 'POST', body: JSON.stringify(data),
                    });
                    modal.remove();
                    window.toast.success(window.ui.t('common.success'));
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        });
    }

    openUserForm() {
        const modal = window.ui.modal('settings.add_account', `
            <form id="user-form">
                <div class="form-group"><label data-i18n="auth.username"></label>
                    <input name="username" class="form-control" required minlength="3"></div>
                <div class="form-group"><label data-i18n="setup.full_name"></label>
                    <input name="full_name" class="form-control"></div>
                <div class="form-group"><label data-i18n="setup.phone"></label>
                    <input name="phone" class="form-control"></div>
                <div class="form-group"><label data-i18n="settings.role"></label>
                    <select name="role" class="form-control">
                        <option value="worker" data-i18n="roles.worker"></option>
                        <option value="admin" data-i18n="roles.admin"></option>
                    </select></div>
                <div class="form-group"><label data-i18n="auth.password"></label>
                    <input name="password" type="password" class="form-control" required minlength="8"></div>
                <button type="submit" class="btn btn-primary btn-block" data-i18n="common.save"></button>
            </form>
        `);
        modal.querySelector('#user-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target));
            await window.ui.submitGuard(e.target.querySelector('button[type=submit]'), async () => {
                try {
                    await window.api.request('/accounts/users/', { method: 'POST', body: JSON.stringify(data) });
                    modal.remove();
                    window.toast.success(window.ui.t('common.success'));
                    await this.loadUsers();
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        });
    }

    openChangePassword() {
        const modal = window.ui.modal('auth.change_password', `
            <form id="password-form">
                <div class="form-group"><label data-i18n="auth.old_password"></label>
                    <input name="old_password" type="password" class="form-control" required></div>
                <div class="form-group"><label data-i18n="auth.new_password"></label>
                    <input name="new_password" type="password" class="form-control" required minlength="8"></div>
                <button type="submit" class="btn btn-primary btn-block" data-i18n="common.save"></button>
            </form>
        `);
        modal.querySelector('#password-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target));
            await window.ui.submitGuard(e.target.querySelector('button[type=submit]'), async () => {
                try {
                    await window.api.request('/accounts/me/password/', { method: 'POST', body: JSON.stringify(data) });
                    modal.remove();
                    window.toast.success(window.ui.t('auth.password_changed'));
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        });
    }
}

window.SettingsComponent = new SettingsComponent();
