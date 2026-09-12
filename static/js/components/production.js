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
        this.taskFilter = '';
        this.workFilter = '';
        const user = window.currentUser;

        container.innerHTML = `
            <div class="tabs">
                <button class="tab-btn active" data-tab="tasks" data-i18n="${user.is_worker ? 'nav.my_tasks' : 'production.tasks'}"></button>
                <button class="tab-btn" data-tab="works" data-i18n="production.works"></button>
                ${user.is_worker ? `<button class="tab-btn" data-tab="earnings" data-i18n="worker_section.my_earnings"></button>` : ''}
            </div>
            ${!user.is_worker ? `<button class="btn btn-primary btn-block u-mb-5" id="add-work-btn" data-i18n="production.add_work"></button>` : ''}
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

    /**
     * Вкладки статуса. Счётчики — по загруженной выборке (page_size=100).
     */
    statusTabs(current, items) {
        return `
            <div class="tabs u-mb-4">
                ${items.map(([value, key, count]) => `
                    <button class="tab-btn ${current === value ? 'active' : ''}"
                            data-status-filter="${value}">
                        <span data-i18n="${key}"></span> (${count})
                    </button>`).join('')}
            </div>`;
    }

    bindStatusTabs(contentEl, kind) {
        contentEl.querySelectorAll('[data-status-filter]').forEach((btn) => {
            btn.addEventListener('click', () => {
                if (kind === 'task') {
                    this.taskFilter = btn.dataset.statusFilter;
                    this.loadTasks();
                } else {
                    this.workFilter = btn.dataset.statusFilter;
                    this.loadWorks();
                }
            });
        });
    }

    /** Переключатель «Бугун / Ҳаммаси» в списке задач работника. */
    bindScopeToggle(contentEl) {
        contentEl.querySelectorAll('[data-scope]').forEach((btn) => {
            btn.addEventListener('click', () => {
                this.taskScope = btn.dataset.scope;
                this.taskFilter = '';
                this.loadTasks();
            });
        });
    }

    async loadTasks() {
        const contentEl = this.container.querySelector('#production-content');
        // Пользователь мог уйти со страницы, пока шёл запрос: контейнера
        // больше нет, рисовать некуда.
        if (window.listStates.gone(contentEl)) return;
        window.listStates.loading(contentEl, window.ui.t('common.loading'));
        try {
            // Экран «Бугунги вазифаларим» (ТЗ): по умолчанию у работника —
            // только актуальные на сегодня задачи (дедлайн сегодня/просрочен/
            // без дедлайна). Переключатель «Бугун / Ҳаммаси» покажет весь список.
            const user0 = window.currentUser;
            const scope = user0.is_worker ? (this.taskScope || 'today') : '';
            const scopeQuery = scope ? `&scope=${scope}` : '';
            const response = await window.api.request(`/production/tasks/?page_size=100${scopeQuery}`);
            const all = response.results || response;
            const filter = this.taskFilter || '';
            const counts = {
                '': all.length,
                pending: all.filter((t) => t.status === 'pending').length,
                accepted: all.filter((t) => ['accepted', 'in_progress'].includes(t.status)).length,
                refused: all.filter((t) => t.status === 'refused').length,
            };
            let tasks = all;
            if (filter === 'pending') tasks = all.filter((t) => t.status === 'pending');
            else if (filter === 'accepted') tasks = all.filter((t) => ['accepted', 'in_progress'].includes(t.status));
            else if (filter === 'refused') tasks = all.filter((t) => t.status === 'refused');
            const tabs = this.statusTabs(filter, [
                ['', 'common.all', counts['']],
                ['pending', 'work_statuses.pending', counts.pending],
                ['accepted', 'work_statuses.accepted', counts.accepted],
                ['refused', 'work_statuses.refused', counts.refused],
            ]);
            // Переключатель «Бугун / Ҳаммаси» — только у работника: фильтр
            // серверный (scope=today), счётчики считаются по загруженной выборке.
            const scopeToggle = user0.is_worker ? `
                <div class="tabs u-mb-4">
                    <button class="tab-btn ${scope === 'today' ? 'active' : ''}" data-scope="today" data-i18n="periods.today"></button>
                    <button class="tab-btn ${scope === '' ? 'active' : ''}" data-scope="" data-i18n="common.all"></button>
                </div>` : '';
            if (!tasks.length) {
                contentEl.innerHTML = scopeToggle + tabs + `<div class="card list-state" data-i18n="common.no_data"></div>`;
                this.bindStatusTabs(contentEl, 'task');
                this.bindScopeToggle(contentEl);
                window.i18n.applyTranslations();
                return;
            }
            const user = window.currentUser;
            contentEl.innerHTML = scopeToggle + tabs + tasks.map((t) => `
                <div class="card">
                    <div class="card-title u-mb-1">
                        <span>#${t.id} ${window.ui.escape(t.title || t.order_product || '')}</span>
                        ${window.ui.workBadge(t.status)}
                    </div>
                    <div class="text-sm text-muted">
                        ${user.is_worker ? '' : `<span data-i18n="production.worker"></span>: ${window.ui.escape(t.worker_name)} · `}
                        ${window.ui.datetime(t.assigned_at)}
                    </div>
                    ${this.taskDetails(t)}
                    ${t.refusal_reason ? `<div class="text-sm text-danger u-mt-2">${window.icon('x', 14)} <span data-i18n="refusal_reasons.${t.refusal_reason}"></span> ${window.ui.escape(t.refusal_comment || '')}</div>` : ''}
                    ${t.refusal_attachment ? `<div class="text-sm u-mt-2">${window.icon('file-text', 14)} <a href="${window.ui.escape(t.refusal_attachment)}" target="_blank" rel="noopener">${window.ui.escape(t.refusal_attachment_name || window.ui.t('production.attachment_optional'))}</a></div>` : ''}
                    ${user.is_worker && t.status === 'pending' ? `
                        <div style="display:flex;gap:10px;margin-top:12px;">
                            <button class="btn btn-success btn-sm u-grow" data-accept="${t.id}" data-i18n="worker_section.accept"></button>
                            <button class="btn btn-danger btn-sm u-grow" data-refuse="${t.id}" data-i18n="worker_section.refuse"></button>
                        </div>` : ''}
                    ${user.is_worker && t.status === 'accepted' ? `
                        <button class="btn btn-primary btn-sm btn-block u-mt-5" data-submit-work="${t.id}" data-i18n="production.send_for_confirmation"></button>` : ''}
                    ${(user.is_owner || user.is_admin) && ['pending', 'accepted'].includes(t.status) ? `
                        <button class="btn btn-secondary btn-sm u-mt-5" data-cancel-task="${t.id}" data-i18n="common.cancel"></button>` : ''}
                </div>`).join('');

            this.bindStatusTabs(contentEl, 'task');
            this.bindScopeToggle(contentEl);
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

    /**
     * Полоса снимков работы: три миниатюры и «+N», как на макете «Ишни
     * тасдиқлаш». Раньше фото не показывалось нигде — админ подтверждал
     * вслепую, хотя подтверждение меняет склад и начисляет рабочему деньги.
     * Работу, присланную без снимков, помечаем явно.
     */
    photoStrip(work) {
        const photos = work.photos || [];
        if (!photos.length) {
            return `<div class="text-sm text-muted u-mt-2"
                         data-i18n="production.no_photos"></div>`;
        }
        const shown = photos.slice(0, 3);
        const rest = photos.length - shown.length;
        return `
            <div class="work-photo-strip u-mt-3">
                ${shown.map((p) => `
                    <a class="work-photo-thumb" href="${window.ui.escape(p.image)}" target="_blank" rel="noopener">
                        <img src="${window.ui.escape(p.image)}" alt="" loading="lazy"
                             onerror="this.parentElement.style.display='none'">
                    </a>`).join('')}
                ${rest > 0 ? `<span class="work-photo-more">+${rest}</span>` : ''}
            </div>`;
    }

    /**
     * Постановка задачи в карточке: описание, срок, цех, размеры, чертёж.
     *
     * Эти поля появились по макетам «Вазифа юбориш» / «Вазифа тафсилоти» —
     * раньше работник видел только номер задачи и товар из заказа и шёл
     * уточнять детали устно. Пустые поля не рисуем, чтобы карточка старой
     * задачи выглядела как раньше.
     */
    taskDetails(t) {
        const rows = [];
        if (t.description) {
            rows.push(`<div class="text-sm u-mt-2">${window.ui.escape(t.description)}</div>`);
        }
        const facts = [];
        if (t.planned_quantity) {
            // План против факта, как в макете «Ишни бажариш».
            facts.push(`<span data-i18n="production.planned_quantity"></span>: `
                + `${window.ui.qty(t.planned_quantity)}`
                + (t.planned_unit ? ` <span data-i18n="units.${t.planned_unit}"></span>` : ''));
        }
        if (t.deadline) {
            facts.push(`<span data-i18n="production.task_deadline"></span>: ${window.ui.datetime(t.deadline)}`);
        }
        if (t.workshop) facts.push(`<span data-i18n="production.workshop"></span>: ${window.ui.escape(t.workshop)}`);
        if (t.size) facts.push(`<span data-i18n="production.task_size"></span>: ${window.ui.escape(t.size)}`);
        if (t.thickness) facts.push(`<span data-i18n="production.task_thickness"></span>: ${window.ui.escape(t.thickness)}`);
        if (facts.length) {
            rows.push(`<div class="text-sm text-muted u-mt-2">${facts.join(' · ')}</div>`);
        }
        if (t.attachment) {
            rows.push(`
                <div class="text-sm u-mt-2">
                    ${window.icon('paperclip', 14)} <a href="${window.ui.escape(t.attachment)}" target="_blank" rel="noopener">
                        ${window.ui.escape(t.attachment_name || window.ui.t('production.task_attachment'))}
                    </a>
                </div>`);
        }
        if (t.is_overdue) {
            rows.push(`<div class="text-sm text-danger u-mt-2">${window.icon('clock', 14)} <span data-i18n="production.overdue"></span></div>`);
        }
        return rows.join('');
    }

    async loadWorks() {
        const contentEl = this.container.querySelector('#production-content');
        // Пользователь мог уйти со страницы, пока шёл запрос: контейнера
        // больше нет, рисовать некуда.
        if (window.listStates.gone(contentEl)) return;
        window.listStates.loading(contentEl, window.ui.t('common.loading'));
        try {
            const response = await window.api.request('/production/works/?page_size=100');
            const all = response.results || response;
            const filter = this.workFilter || '';
            const counts = {
                '': all.length,
                awaiting_confirmation: all.filter((w) => w.status === 'awaiting_confirmation').length,
                confirmed: all.filter((w) => w.status === 'confirmed').length,
                rejected: all.filter((w) => w.status === 'rejected').length,
            };
            const works = filter ? all.filter((w) => w.status === filter) : all;
            const tabs = this.statusTabs(filter, [
                ['', 'common.all', counts['']],
                ['awaiting_confirmation', 'work_statuses.awaiting_confirmation', counts.awaiting_confirmation],
                ['confirmed', 'work_statuses.confirmed', counts.confirmed],
                ['rejected', 'work_statuses.rejected', counts.rejected],
            ]);
            if (!works.length) {
                contentEl.innerHTML = tabs + `<div class="card list-state" data-i18n="common.no_data"></div>`;
                this.bindStatusTabs(contentEl, 'work');
                window.i18n.applyTranslations();
                return;
            }
            const user = window.currentUser;
            const canConfirm = user.is_owner || user.is_admin;
            contentEl.innerHTML = tabs + works.map((w) => `
                <div class="card">
                    <div class="card-title u-mb-1">
                        <span>#${w.id} ${window.ui.escape(w.product_name || '-')}</span>
                        ${window.ui.workBadge(w.status)}
                    </div>
                    <div class="text-sm text-muted">
                        ${user.is_worker ? '' : `${window.ui.escape(w.worker_name)} · `}
                        ${window.ui.qty(w.quantity)} <span data-i18n="units.${w.unit}"></span> · ${window.ui.datetime(w.created_at)}
                    </div>
                    ${Number(w.defect_quantity) > 0 ? `
                        <div class="text-sm text-danger u-mt-1">
                            <span data-i18n="production.defect_quantity"></span>: ${window.ui.qty(w.defect_quantity)}
                        </div>` : ''}
                    ${this.photoStrip(w)}
                    ${w.comment ? `<div class="text-sm u-mt-2">${window.ui.escape(w.comment)}</div>` : ''}
                    ${w.rejection_reason ? `<div class="text-sm text-danger u-mt-2">${window.icon('x', 14)} ${window.ui.escape(w.rejection_reason)}</div>` : ''}
                    ${w.labor_cost !== undefined && w.status === 'confirmed' ? `
                        <div class="text-sm text-success font-bold u-mt-2">+ ${window.ui.money(w.labor_cost)}</div>` : ''}
                    ${w.status === 'confirmed' ? `
                        <div class="text-xs text-muted u-mt-1">
                            ${window.ui.t('production.confirmed_by')}: ${window.ui.escape(w.confirmed_by_name || '—')} · ${window.ui.datetime(w.confirmed_at)}
                        </div>` : ''}
                    ${canConfirm && w.status === 'awaiting_confirmation' ? `
                        <div style="display:flex;gap:10px;margin-top:12px;">
                            <button class="btn btn-success btn-sm u-grow" data-confirm="${w.id}" data-i18n="production.confirm"></button>
                            <button class="btn btn-danger btn-sm u-grow" data-reject="${w.id}" data-i18n="production.reject"></button>
                        </div>` : ''}
                </div>`).join('');

            this.bindStatusTabs(contentEl, 'work');
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
                        <div class="metric-value u-fs-17">${window.ui.money(data.total_earned)}</div>
                    </div>
                    <div class="metric-card blue">
                        <div class="metric-title" data-i18n="worker_section.paid_out"></div>
                        <div class="metric-value u-fs-17">${window.ui.money(data.paid_out)}</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-title" data-i18n="worker_section.this_month"></div>
                        <div class="metric-value u-fs-17">${window.ui.money(data.this_month)}</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-title" data-i18n="worker_section.last_month"></div>
                        <div class="metric-value u-fs-17">${window.ui.money(data.last_month)}</div>
                    </div>
                </div>
                <div class="card u-between">
                    <span data-i18n="worker_section.remaining"></span>
                    <span class="metric-value u-fs-20">${window.ui.money(data.remaining)}</span>
                </div>
                ${(data.payments || []).length ? `
                    <div class="section-title" data-i18n="worker_section.payment_history"></div>
                    <div class="list-group list-group-compact">
                        ${(data.payments || []).map((p) => `
                            <div class="list-row u-cursor-default">
                                <div class="u-minw-0">
                                    <div class="u-strong">${window.ui.escape(window.ui.t('payment_types.' + p.payment_type))}</div>
                                    <div class="text-sm text-muted">${window.ui.date(p.payment_date)}</div>
                                </div>
                                <span class="font-bold text-success">+${window.ui.money(p.amount)}</span>
                            </div>`).join('')}
                    </div>` : ''}`;
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
                <!-- Фото-довод (макет «Илова (ихтиёрий)»): необязательный снимок,
                     например бракованного материала. -->
                <div class="form-group"><label data-i18n="production.attachment_optional"></label>
                    <input type="file" name="attachment" class="form-control" accept="image/*,.pdf"></div>
                <button type="submit" class="btn btn-danger btn-block" data-i18n="worker_section.refuse"></button>
            </form>
        `);
        modal.querySelector('#refuse-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const form = e.target;
            // Есть файл → multipart/form-data (сервер принимает оба варианта);
            // нет файла → прежний JSON, чтобы не менять поведение без причины.
            const fileInput = form.querySelector('input[name=attachment]');
            const hasFile = fileInput && fileInput.files && fileInput.files.length > 0;
            let body;
            if (hasFile) {
                body = new FormData(form);
            } else {
                const data = Object.fromEntries(new FormData(form));
                delete data.attachment; // файл не выбран — уходим JSON-ом
                body = JSON.stringify(data);
            }
            await window.ui.submitGuard(form.querySelector('button[type=submit]'), async () => {
                try {
                    await window.api.request(`/production/tasks/${id}/refuse/`, { method: 'POST', body });
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
                        <option value="" data-i18n="common.select"></option>
                        ${products.map((p) => `<option value="${p.id}">${window.ui.escape(p.name)}</option>`).join('')}
                    </select></div>
                <div class="form-group" id="work-operation-group" style="display:none;">
                    <label data-i18n="production.operation"></label>
                    <select name="operation" id="work-operation" class="form-control"></select>
                    <small class="text-muted" data-i18n="production.operation_hint"></small>
                </div>
                <div id="work-pay-info" class="alert-box alert-box-info" style="display:none;"></div>
                <div class="u-grid-2">
                    <div class="form-group"><label data-i18n="production.quantity"></label>
                        <input name="quantity" type="number" step="0.001" min="0.001" class="form-control" required></div>
                    <div class="form-group"><label data-i18n="warehouse.unit"></label>
                        <select name="unit" class="form-control">${window.ui.unitOptions('izdelie')}</select></div>
                </div>
                <div class="form-group"><label data-i18n="production.defect_quantity"></label>
                    <input name="defect_quantity" type="number" step="0.001" min="0" value="0" class="form-control">
                    <small class="text-muted" data-i18n="production.defect_hint"></small></div>
                <div style="display:none;">
                </div>
                <div class="form-group"><label data-i18n="warehouse.comment"></label>
                    <textarea name="comment" class="form-control" rows="2"></textarea></div>
                <div class="form-group"><label data-i18n="production.attach_photo"></label>
                    <input name="uploaded_photos" type="file" accept="image/*" multiple class="form-control">
                    <small class="text-muted" data-i18n="production.photo_hint"></small>
                    <div id="work-photo-preview" class="work-photo-preview"></div></div>
                <button type="submit" class="btn btn-primary btn-block" data-i18n="production.send_for_confirmation"></button>
            </form>
        `);

        // Операция работы: подтягиваем ставки выбранного товара и предлагаем
        // выбрать операцию — по ней при подтверждении начислится оплата
        // (раньше бралась ставка «по алфавиту» из всех ставок товара).
        const productSelect = modal.querySelector('select[name=product]');
        const operationGroup = modal.querySelector('#work-operation-group');
        const operationSelect = modal.querySelector('#work-operation');
        const payInfo = modal.querySelector('#work-pay-info');
        const quantityInput = modal.querySelector('input[name=quantity]');
        let currentRates = [];
        const renderPayInfo = () => {
            if (!productSelect.value) {
                payInfo.style.display = 'none';
                return;
            }
            if (!currentRates.length) {
                // Ставки нет: работа уйдёт на подтверждение, но не «бесплатная» —
                // владелец задаст ставку или назначит сумму вручную.
                payInfo.className = 'alert-box alert-box-warning';
                payInfo.textContent = window.ui.t('production.no_labor_rate');
                payInfo.style.display = '';
                return;
            }
            const op = operationSelect.value;
            const rate = op
                ? currentRates.find((r) => r.operation === op)
                : currentRates.length === 1 ? currentRates[0] : null;
            if (!rate) {
                payInfo.style.display = 'none';
                return;
            }
            const qty = Number(quantityInput.value) || 0;
            const total = (Number(rate.rate_per_unit) * qty).toLocaleString('ru-RU', { maximumFractionDigits: 2 });
            payInfo.className = 'alert-box alert-box-info';
            payInfo.textContent = window.ui.t('production.expected_pay')
                .replace('{rate}', window.ui.qty(rate.rate_per_unit))
                .replace('{total}', total);
            payInfo.style.display = '';
        };
        const loadOperations = async () => {
            const pid = productSelect.value;
            if (!pid) {
                operationGroup.style.display = 'none';
                currentRates = [];
                renderPayInfo();
                return;
            }
            try {
                const resp = await window.api.request(`/finance/labor-rates/?product=${pid}`);
                currentRates = resp.results || resp;
                const ops = [...new Set(currentRates.map((r) => r.operation))];
                operationSelect.innerHTML = ops
                    .map((op) => `<option value="${op}" data-i18n="operations.${op}"></option>`)
                    .join('');
                window.i18n.applyTranslations();
                operationSelect.required = ops.length > 1;
                operationGroup.style.display = ops.length ? '' : 'none';
                renderPayInfo();
            } catch (error) {
                operationGroup.style.display = 'none';
                currentRates = [];
                renderPayInfo();
            }
        };
        productSelect.addEventListener('change', loadOperations);
        operationSelect.addEventListener('change', renderPayInfo);
        quantityInput.addEventListener('input', renderPayInfo);

        // Превью выбранных снимков с крестиком, как на макете «Ишни якунлаш».
        const photoInputEl = modal.querySelector('input[name=uploaded_photos]');
        const previewEl = modal.querySelector('#work-photo-preview');
        let chosenFiles = [];
        const renderPreview = () => {
            previewEl.innerHTML = chosenFiles.map((file, index) => `
                <div class="work-photo-thumb">
                    <img src="${URL.createObjectURL(file)}" alt="">
                    <button type="button" class="work-photo-remove" data-remove="${index}"
                            aria-label="${window.ui.escape(window.ui.t('common.delete'))}">×</button>
                </div>`).join('');
            previewEl.querySelectorAll('[data-remove]').forEach((btn) => {
                btn.addEventListener('click', () => {
                    chosenFiles.splice(Number(btn.dataset.remove), 1);
                    syncInput();
                    renderPreview();
                });
            });
        };
        const syncInput = () => {
            const dt = new DataTransfer();
            chosenFiles.forEach((file) => dt.items.add(file));
            photoInputEl.files = dt.files;
        };
        photoInputEl.addEventListener('change', () => {
            chosenFiles = [...photoInputEl.files];
            renderPreview();
        });

        modal.querySelector('#work-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const form = e.target;
            const photoInput = form.querySelector('input[type=file]');
            const formData = new FormData(form);

            if (task) formData.set('task', task.id);
            if (!user.is_worker) formData.set('worker', user.id);

            // Галерея: каждый снимок уходит отдельным значением uploaded_photos,
            // сжатый тем же ui.compressImage.
            formData.delete('uploaded_photos');
            const chosen = photoInput ? [...photoInput.files] : [];
            for (const file of chosen) {
                formData.append('uploaded_photos', await window.ui.compressImage(file));
            }
            // Макет просит два снимка. Правило мягкое: предупреждаем, но пускаем —
            // рабочий без камеры или со слабым интернетом не должен застрять.
            if (chosen.length < 2) {
                window.toast.info(window.ui.t('production.photo_hint'));
            }

            await window.ui.submitGuard(form.querySelector('button[type=submit]'), async () => {
                try {
                    await window.api.request('/production/works/', { method: 'POST', body: formData });
                    window.ui.closeModal(modal);
                    window.toast.success(window.ui.t('production.work_submitted'));
                    this.tab = 'works';
                    this.container.querySelectorAll('[data-tab]').forEach((b) => b.classList.toggle('active', b.dataset.tab === 'works'));
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
            <div id="confirm-work-details"></div>
            <p class="text-sm text-muted u-mb-5" data-i18n="production.confirm_hint"></p>
            <form id="confirm-form">
                ${isOwner ? `
                    <div class="form-group"><label data-i18n="production.labor_cost"></label>
                        <input name="labor_cost" type="number" step="0.01" min="0" class="form-control" placeholder="${window.ui.t('production.labor_cost_auto')}"></div>` : ''}
                <button type="submit" class="btn btn-success btn-block" data-i18n="production.confirm"></button>
            </form>
        `);
        // Показываем, что именно подтверждается: товар, количество, брак,
        // снимки. Подтверждение меняет склад и начисляет деньги — раньше
        // админ жал кнопку вслепую, не видя самой работы.
        window.api.request(`/production/works/${id}/`).then((w) => {
            if (!modal.isConnected) return;
            const details = modal.querySelector('#confirm-work-details');
            const payRow = w.labor_rate
                ? `<div class="text-sm font-bold u-mt-2">${window.ui.escape(
                    window.ui.t('production.pay_calc')
                        .replace('{rate}', window.ui.qty(w.labor_rate))
                        .replace('{qty}', window.ui.qty(w.quantity))
                        .replace('{total}', window.ui.qty(Number(w.labor_rate) * Number(w.quantity))))}</div>`
                : `<div class="alert-box alert-box-warning" style="margin-bottom:0;margin-top:8px;" data-i18n="production.confirm_no_rate_hint"></div>`;
            details.innerHTML = `
                <div class="card" style="box-shadow:none;border:1px solid var(--border);margin-bottom:12px;padding:12px;">
                    <div class="text-sm font-bold">${window.ui.escape(w.product_name || '-')} × ${window.ui.qty(w.quantity)} <span data-i18n="units.${w.unit}"></span></div>
                    <div class="text-sm text-muted u-mt-1">${window.ui.escape(w.worker_name)} · ${window.ui.datetime(w.created_at)}</div>
                    ${Number(w.defect_quantity) > 0 ? `
                        <div class="text-sm text-danger u-mt-1"><span data-i18n="production.defect_quantity"></span>: ${window.ui.qty(w.defect_quantity)}</div>` : ''}
                    ${this.photoStrip(w)}
                    ${w.comment ? `<div class="text-sm u-mt-2">${window.ui.escape(w.comment)}</div>` : ''}
                    ${payRow}
                </div>`;
            window.i18n.applyTranslations();
        }).catch(() => {
            if (!modal.isConnected) return;
            modal.querySelector('#confirm-work-details').innerHTML =
                `<div class="alert-box u-mb-5"><span data-i18n="common.error"></span></div>`;
            window.i18n.applyTranslations();
        });
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
