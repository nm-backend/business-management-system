/**
 * Аудит: журнал действий для владельца.
 * Таблица с фильтром по типу действия, роли, дате.
 */
class AuditComponent {
    async render(container) {
        document.getElementById('page-title').setAttribute('data-i18n', 'settings.audit_log');
        window.i18n.applyTranslations();
        this.container = container;
        this.page = 1;
        this.filters = { action: '', actor_role: '' };
        await this.load();
    }

    async load() {
        const params = new URLSearchParams({ page: this.page, ordering: '-created_at' });
        if (this.filters.action) params.set('action', this.filters.action);
        if (this.filters.actor_role) params.set('actor_role', this.filters.actor_role);

        this.container.innerHTML = `
            <div style="display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap;">
                <select class="form-control" id="audit-filter-action" style="width:auto;min-width:140px;flex:1;">
                    <option value="">${window.ui.t('common.all')}</option>
                    <option value="login" ${this.filters.action === 'login' ? 'selected' : ''}>${window.ui.t('audit.login')}</option>
                    <option value="logout" ${this.filters.action === 'logout' ? 'selected' : ''}>${window.ui.t('audit.logout')}</option>
                    <option value="create" ${this.filters.action === 'create' ? 'selected' : ''}>${window.ui.t('audit.create')}</option>
                    <option value="update" ${this.filters.action === 'update' ? 'selected' : ''}>${window.ui.t('audit.update')}</option>
                    <option value="archive" ${this.filters.action === 'archive' ? 'selected' : ''}>${window.ui.t('audit.archive')}</option>
                    <option value="activate" ${this.filters.action === 'activate' ? 'selected' : ''}>${window.ui.t('audit.activate')}</option>
                    <option value="deactivate" ${this.filters.action === 'deactivate' ? 'selected' : ''}>${window.ui.t('audit.deactivate')}</option>
                    <option value="delete" ${this.filters.action === 'delete' ? 'selected' : ''}>${window.ui.t('audit.delete')}</option>
                    <option value="change_password" ${this.filters.action === 'change_password' ? 'selected' : ''}>${window.ui.t('audit.change_password')}</option>
                    <option value="reset_password" ${this.filters.action === 'reset_password' ? 'selected' : ''}>${window.ui.t('audit.reset_password')}</option>
                    <option value="access_key_issued" ${this.filters.action === 'access_key_issued' ? 'selected' : ''}>${window.ui.t('audit.access_key_issued')}</option>
                    <option value="access_key_redeemed" ${this.filters.action === 'access_key_redeemed' ? 'selected' : ''}>${window.ui.t('audit.access_key_redeemed')}</option>
                    <option value="token_theft_detected" ${this.filters.action === 'token_theft_detected' ? 'selected' : ''}>${window.ui.t('audit.token_theft_detected')}</option>
                </select>
                <select class="form-control" id="audit-filter-role" style="width:auto;min-width:120px;flex:1;">
                    <option value="">${window.ui.t('common.all')}</option>
                    <option value="owner" ${this.filters.actor_role === 'owner' ? 'selected' : ''}>${window.ui.t('roles.owner')}</option>
                    <option value="admin" ${this.filters.actor_role === 'admin' ? 'selected' : ''}>${window.ui.t('roles.admin')}</option>
                    <option value="worker" ${this.filters.actor_role === 'worker' ? 'selected' : ''}>${window.ui.t('roles.worker')}</option>
                </select>
            </div>
            <div class="table-scroll">
                <table class="data-table">
                    <thead><tr>
                        <th data-i18n="common.date"></th>
                        <th data-i18n="common.actions"></th>
                        <th data-i18n="auth.username"></th>
                        <th data-i18n="settings.role"></th>
                        <th data-i18n="orders.product"></th>
                        <th data-i18n="common.details"></th>
                    </tr></thead>
                    <tbody id="audit-tbody">
                        <tr><td colspan="6"><div class="list-state list-state-loading"><span class="spinner"></span></div></td></tr>
                    </tbody>
                </table>
            </div>
            <div class="pagination" id="audit-pagination" style="display:none;"></div>
        `;
        window.i18n.applyTranslations();

        this.container.querySelector('#audit-filter-action').addEventListener('change', (e) => {
            this.filters.action = e.target.value;
            this.page = 1;
            this.load();
        });
        this.container.querySelector('#audit-filter-role').addEventListener('change', (e) => {
            this.filters.actor_role = e.target.value;
            this.page = 1;
            this.load();
        });

        try {
            const response = await window.api.request(`/audit/logs/?${params}`);
            const rows = response.results || [];
            const tbody = this.container.querySelector('#audit-tbody');

            if (!rows.length) {
                tbody.innerHTML = `<tr><td colspan="6"><div class="list-state list-state-empty"><span>${window.ui.t('common.no_data')}</span></div></td></tr>`;
                return;
            }

            const actionIcons = {
                login: '🔓', logout: '🔒', create: '➕', update: '✏️',
                archive: '📦', activate: '✅', deactivate: '⛔',
                access_key_issued: '🔑', reset_password: '🔄', change_password: '🔐',
                delete: '🗑️', token_theft_detected: '🚨', access_key_redeemed: '🔓',
            };

            tbody.innerHTML = rows.map((r) => `
                <tr>
                    <td style="white-space:nowrap;font-size:11px;">${window.ui.datetime(r.created_at)}</td>
                    <td><span style="font-size:16px;">${actionIcons[r.action] || '📝'}</span></td>
                    <td style="font-weight:500;">${window.ui.escape(r.actor_username || 'system')}</td>
                    <td><span class="badge badge-new">${window.ui.t('roles.' + r.actor_role) || r.actor_role}</span></td>
                    <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${window.ui.escape(r.object_repr || r.object_type)}</td>
                    <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px;color:var(--text-muted);">
                        ${r.object_type}${r.object_id ? ' #' + r.object_id : ''}
                    </td>
                </tr>
            `).join('');

            // Пагинация
            const pagination = this.container.querySelector('#audit-pagination');
            const pageSize = response.results?.length || 20;
            const totalPages = Math.ceil(response.count / pageSize);
            if (totalPages > 1) {
                pagination.style.display = 'flex';
                pagination.innerHTML = `
                    <button class="btn btn-sm btn-secondary" ${this.page <= 1 ? 'disabled' : ''} id="audit-prev">← ${window.ui.t('common.previous')}</button>
                    <span style="padding:8px 12px;font-weight:600;">${this.page} / ${totalPages}</span>
                    <button class="btn btn-sm btn-secondary" ${this.page >= totalPages ? 'disabled' : ''} id="audit-next">${window.ui.t('common.next')} →</button>
                `;
                pagination.querySelector('#audit-prev')?.addEventListener('click', () => { this.page--; this.load(); });
                pagination.querySelector('#audit-next')?.addEventListener('click', () => { this.page++; this.load(); });
            } else {
                pagination.style.display = 'none';
            }
            window.i18n.applyTranslations();
        } catch (e) {
            this.container.querySelector('#audit-tbody').innerHTML = `
                <tr><td colspan="6"><div class="list-state list-state-error">${window.ui.t('common.error_loading')}</div></td></tr>`;
        }
    }
}

window.AuditComponent = new AuditComponent();
