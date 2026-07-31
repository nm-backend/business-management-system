/**
 * Производство.
 * Worker: мои задачи (принять/отказаться), мои работы, добавить работу, заработок.
 * Owner/Admin: задачи работников и подтверждение работ (меняет склад).
 */
class ProductionComponent {
    async render(container) {
        document.getElementById('page-title').setAttribute('data-i18n', 'production.title');
        this.container = container;
        this.tab = 'tasks';
        const user = window.currentUser;

        container.innerHTML = `
            <div class="tabs">
                <button class="tab-btn active" data-tab="tasks" data-i18n="${user.is_worker ? 'nav.my_tasks' : 'production.tasks'}"></button>
                <button class="tab-btn" data-tab="works" data-i18n="production.works"></button>
                ${user.is_worker ? `<button class="tab-btn" data-tab="earnings" data-i18n="worker_section.my_earnings"></button>` : ''}
            </div>
            ${!user.is_manager ? `<button class="btn btn-primary btn-block" id="add-work-btn" style="margin-bottom:12px;" data-i18n="production.add_work"></button>` : ''}
            <div id="production-content"></div>
        `;

        container.querySelectorAll('.tab-btn').forEach((btn) => {
            btn.addEventListener('click', () => {
                container.querySelectorAll('.tab-btn').forEach((b) => b.classList.remove('active'));
                btn.classList.add('active');
                this.tab = btn.dataset.tab;
                this.loadTab();
            });
        });
        const addWorkBtn = container.querySelector('#add-work-btn');
        if (addWorkBtn) addWorkBtn.addEventListener('click', () => this.openWorkForm());

        window.i18n.applyTranslations();
        await this.loadTab();
    }

    loadTab() {
        if (this.tab === 'tasks') return this.loadTasks();
        if (this.tab === 'works') return this.loadWorks();
        return this.loadEarnings();
    }

    async loadTasks() {
        const contentEl = this.container.querySelector('#production-content');
        // Пользователь мог уйти со страницы, пока шёл запрос: контейнера
        // больше нет, рисовать некуда.
        if (window.listStates.gone(contentEl)) return;
        window.listStates.loading(contentEl, window.ui.t('common.loading'));
        try {
            const response = await window.api.request('/production/tasks/');
            const tasks = response.results || response;
            if (!tasks.length) {
                window.listStates.empty(contentEl, window.ui.t('common.no_data'));
                return;
            }
            const user = window.currentUser;
            contentEl.innerHTML = tasks.map((t) => `
                <div class="card">
                    <div class="card-title" style="margin-bottom:4px;">
                        <span>#${t.id} ${window.ui.escape(t.order_product || '')}</span>
                        ${window.ui.workBadge(t.status)}
                    </div>
                    <div class="text-sm text-muted">
                        ${user.is_worker ? '' : `<span data-i18n="production.worker"></span>: ${window.ui.escape(t.worker_name)} · `}
                        ${window.ui.datetime(t.assigned_at)}
                    </div>
                    ${t.refusal_reason ? `<div class="text-sm text-danger" style="margin-top:6px;">✕ <span data-i18n="refusal_reasons.${t.refusal_reason}"></span> ${window.ui.escape(t.refusal_comment || '')}</div>` : ''}
                    ${user.is_worker && t.status === 'pending' ? `
                        <div style="display:flex;gap:10px;margin-top:12px;">
                            <button class="btn btn-success btn-sm" style="flex:1;" data-accept="${t.id}" data-i18n="worker_section.accept"></button>
                            <button class="btn btn-danger btn-sm" style="flex:1;" data-refuse="${t.id}" data-i18n="worker_section.refuse"></button>
                        </div>` : ''}
                    ${user.is_worker && t.status === 'accepted' ? `
                        <button class="btn btn-primary btn-sm btn-block" style="margin-top:12px;" data-submit-work="${t.id}" data-i18n="production.send_for_confirmation"></button>` : ''}
                    ${(user.is_owner || user.is_admin) && ['pending', 'accepted'].includes(t.status) ? `
                        <button class="btn btn-secondary btn-sm" style="margin-top:12px;" data-cancel-task="${t.id}" data-i18n="common.cancel"></button>` : ''}
                </div>`).join('');

            contentEl.querySelectorAll('[data-accept]').forEach((b) => b.addEventListener('click', () => this.acceptTask(b.dataset.accept)));
            contentEl.querySelectorAll('[data-refuse]').forEach((b) => b.addEventListener('click', () => this.refuseTask(b.dataset.refuse)));
            contentEl.querySelectorAll('[data-cancel-task]').forEach((b) => b.addEventListener('click', () => this.cancelTask(b.dataset.cancelTask)));
            contentEl.querySelectorAll('[data-submit-work]').forEach((b) => b.addEventListener('click', () => {
                const task = tasks.find((t) => t.id === Number(b.dataset.submitWork));
                this.openWorkForm(task);
            }));
            window.i18n.applyTranslations();
        } catch (e) {
            window.listStates.error(contentEl, window.ui.t('common.error'), () => this.loadTasks());
        }
    }

    async loadWorks() {
        const contentEl = this.container.querySelector('#production-content');
        // Пользователь мог уйти со страницы, пока шёл запрос: контейнера
        // больше нет, рисовать некуда.
        if (window.listStates.gone(contentEl)) return;
        window.listStates.loading(contentEl, window.ui.t('common.loading'));
        try {
            const response = await window.api.request('/production/works/');
            const works = response.results || response;
            if (!works.length) {
                window.listStates.empty(contentEl, window.ui.t('common.no_data'));
                return;
            }
            const user = window.currentUser;
            const canConfirm = user.is_owner || user.is_admin;
            contentEl.innerHTML = works.map((w) => `
                <div class="card">
                    <div class="card-title" style="margin-bottom:4px;">
                        <span>#${w.id} ${window.ui.escape(w.product_name || '-')}</span>
                        ${window.ui.workBadge(w.status)}
                    </div>
                    <div class="text-sm text-muted">
                        ${user.is_worker ? '' : `${window.ui.escape(w.worker_name)} · `}
                        ${window.ui.qty(w.quantity)} <span data-i18n="units.${w.unit}"></span> · ${window.ui.datetime(w.created_at)}
                    </div>
                    ${w.comment ? `<div class="text-sm" style="margin-top:6px;">${window.ui.escape(w.comment)}</div>` : ''}
                    ${w.rejection_reason ? `<div class="text-sm text-danger" style="margin-top:6px;">✕ ${window.ui.escape(w.rejection_reason)}</div>` : ''}
                    ${w.labor_cost !== undefined && w.status === 'confirmed' ? `
                        <div class="text-sm text-success font-bold" style="margin-top:6px;">+ ${window.ui.money(w.labor_cost)}</div>` : ''}
                    ${canConfirm && w.status === 'awaiting_confirmation' ? `
                        <div style="display:flex;gap:10px;margin-top:12px;">
                            <button class="btn btn-success btn-sm" style="flex:1;" data-confirm="${w.id}" data-i18n="production.confirm"></button>
                            <button class="btn btn-danger btn-sm" style="flex:1;" data-reject="${w.id}" data-i18n="production.reject"></button>
                        </div>` : ''}
                </div>`).join('');

            contentEl.querySelectorAll('[data-confirm]').forEach((b) => b.addEventListener('click', () => this.confirmWork(b.dataset.confirm)));
            contentEl.querySelectorAll('[data-reject]').forEach((b) => b.addEventListener('click', () => this.rejectWork(b.dataset.reject)));
            window.i18n.applyTranslations();
        } catch (e) {
            window.listStates.error(contentEl, window.ui.t('common.error'), () => this.loadWorks());
        }
    }

    async loadEarnings() {
        const contentEl = this.container.querySelector('#production-content');
        // Пользователь мог уйти со страницы, пока шёл запрос: контейнера
        // больше нет, рисовать некуда.
        if (window.listStates.gone(contentEl)) return;
        window.listStates.loading(contentEl, window.ui.t('common.loading'));
        try {
            const data = await window.api.request('/production/works/my_earnings/');
            contentEl.innerHTML = `
                <div class="metrics-grid">
                    <div class="metric-card green">
                        <div class="metric-title" data-i18n="worker_section.total_earned"></div>
                        <div class="metric-value" style="font-size:17px;">${window.ui.money(data.total_earned)}</div>
                    </div>
                    <div class="metric-card blue">
                        <div class="metric-title" data-i18n="worker_section.paid_out"></div>
                        <div class="metric-value" style="font-size:17px;">${window.ui.money(data.paid_out)}</div>
                    </div>
                </div>
                <div class="card" style="display:flex;justify-content:space-between;align-items:center;">
                    <span data-i18n="worker_section.remaining"></span>
                    <span class="metric-value" style="font-size:20px;">${window.ui.money(data.remaining)}</span>
                </div>`;
            window.i18n.applyTranslations();
        } catch (e) {
            window.listStates.error(contentEl, window.ui.t('common.error'), () => this.loadEarnings());
        }
    }

    async acceptTask(id) {
        try {
            await window.api.request(`/production/tasks/${id}/accept/`, { method: 'POST' });
            window.toast.success(window.ui.t('common.success'));
            await this.loadTasks();
        } catch (error) {
            window.toast.error(window.ui.errorText(error));
        }
    }

    refuseTask(id) {
        const reasons = ['material_insufficient', 'no_time', 'wrong_size', 'need_helper', 'equipment_busy', 'other'];
        const modal = window.ui.modal('worker_section.refuse', `
            <form id="refuse-form">
                <div class="form-group"><label data-i18n="production.rejection_reason"></label>
                    <select name="reason" class="form-control" required>
                        ${reasons.map((r) => `<option value="${r}" data-i18n="refusal_reasons.${r}"></option>`).join('')}
                    </select></div>
                <div class="form-group"><label data-i18n="warehouse.comment"></label>
                    <textarea name="comment" class="form-control" rows="2"></textarea></div>
                <button type="submit" class="btn btn-danger btn-block" data-i18n="worker_section.refuse"></button>
            </form>
        `);
        modal.querySelector('#refuse-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target));
            await window.ui.submitGuard(e.target.querySelector('button[type=submit]'), async () => {
                try {
                    await window.api.request(`/production/tasks/${id}/refuse/`, { method: 'POST', body: JSON.stringify(data) });
                    window.ui.closeModal(modal);
                    window.toast.success(window.ui.t('common.success'));
                    await this.loadTasks();
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        });
    }

    async cancelTask(id) {
        if (!(await window.confirmation.confirm(window.ui.t('production.cancel_task_confirm'), window.ui.t('common.cancel')))) return;
        try {
            await window.api.request(`/production/tasks/${id}/cancel/`, { method: 'POST' });
            window.toast.success(window.ui.t('common.success'));
            await this.loadTasks();
        } catch (error) {
            window.toast.error(window.ui.errorText(error));
        }
    }

    /** Сдача работы: работник указывает товар, количество, комментарий. */
    async openWorkForm(task = null) {
        const productsResp = await window.api.request('/warehouse/finished-products/?is_archived=false');
        const products = productsResp.results || productsResp;
        const user = window.currentUser;

        const modal = window.ui.modal('production.add_work', `
            <form id="work-form">
                <div class="form-group"><label data-i18n="production.product"></label>
                    <select name="product" class="form-control" required>
                        <option value=""></option>
                        ${products.map((p) => `<option value="${p.id}">${window.ui.escape(p.name)}</option>`).join('')}
                    </select></div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                    <div class="form-group"><label data-i18n="production.quantity"></label>
                        <input name="quantity" type="number" step="0.001" min="0.001" class="form-control" required></div>
                    <div class="form-group"><label data-i18n="warehouse.unit"></label>
                        <select name="unit" class="form-control">${window.ui.unitOptions('izdelie')}</select></div>
                </div>
                <div class="form-group"><label data-i18n="warehouse.comment"></label>
                    <textarea name="comment" class="form-control" rows="2"></textarea></div>
                <div class="form-group"><label data-i18n="production.attach_photo"></label>
                    <input name="photo" type="file" accept="image/*" class="form-control"></div>
                <button type="submit" class="btn btn-primary btn-block" data-i18n="production.send_for_confirmation"></button>
            </form>
        `);

        modal.querySelector('#work-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const form = e.target;
            const photoInput = form.querySelector('input[type=file]');
            const formData = new FormData(form);

            if (task) formData.set('task', task.id);
            if (!user.is_worker) formData.set('worker', user.id);

            if (photoInput && photoInput.files[0]) {
                const compressed = await window.ui.compressImage(photoInput.files[0]);
                formData.set('photo', compressed);
            }

            await window.ui.submitGuard(form.querySelector('button[type=submit]'), async () => {
                try {
                    await window.api.request('/production/works/', { method: 'POST', body: formData });
                    window.ui.closeModal(modal);
                    window.toast.success(window.ui.t('production.work_submitted'));
                    this.tab = 'works';
                    this.container.querySelectorAll('.tab-btn').forEach((b) => b.classList.toggle('active', b.dataset.tab === 'works'));
                    await this.loadWorks();
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        });
    }

    /** Подтверждение работы: owner может указать оплату, иначе по ставке. */
    confirmWork(id) {
        const isOwner = window.currentUser.is_owner;
        const modal = window.ui.modal('production.confirm', `
            <p class="text-sm text-muted" style="margin-bottom:12px;" data-i18n="production.confirm_hint"></p>
            <form id="confirm-form">
                ${isOwner ? `
                    <div class="form-group"><label data-i18n="production.labor_cost"></label>
                        <input name="labor_cost" type="number" step="0.01" min="0" class="form-control" placeholder="${window.ui.t('production.labor_cost_auto')}"></div>` : ''}
                <button type="submit" class="btn btn-success btn-block" data-i18n="production.confirm"></button>
            </form>
        `);
        modal.querySelector('#confirm-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target));
            if (!data.labor_cost) delete data.labor_cost;
            await window.ui.submitGuard(e.target.querySelector('button[type=submit]'), async () => {
                try {
                    await window.api.request(`/production/works/${id}/confirm/`, { method: 'POST', body: JSON.stringify(data) });
                    window.ui.closeModal(modal);
                    window.toast.success(window.ui.t('production.work_confirmed'));
                    await this.loadWorks();
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        });
    }

    rejectWork(id) {
        const modal = window.ui.modal('production.reject', `
            <form id="reject-form">
                <div class="form-group"><label data-i18n="production.rejection_reason"></label>
                    <textarea name="reason" class="form-control" rows="2" required></textarea></div>
                <button type="submit" class="btn btn-danger btn-block" data-i18n="production.reject"></button>
            </form>
        `);
        modal.querySelector('#reject-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target));
            await window.ui.submitGuard(e.target.querySelector('button[type=submit]'), async () => {
                try {
                    await window.api.request(`/production/works/${id}/reject/`, { method: 'POST', body: JSON.stringify(data) });
                    window.ui.closeModal(modal);
                    window.toast.success(window.ui.t('production.work_rejected'));
                    await this.loadWorks();
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        });
    }
}

window.ProductionComponent = new ProductionComponent();
