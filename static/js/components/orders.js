/**
 * Заказы: список с фильтром по статусу, красные карточки при нехватке
 * материала или неоплате, создание (owner/admin), карточка заказа с
 * действиями: отправить работнику, выдать, отменить, принять оплату (owner).
 */
class OrdersComponent {
    async render(container) {
        document.getElementById('page-title').setAttribute('data-i18n', 'orders.title');
        this.currentStatus = 'all';
        const user = window.currentUser;
        const canEdit = user.is_owner || user.is_admin;

        const statuses = ['all', 'new', 'sent_to_worker', 'in_progress', 'awaiting_confirmation', 'ready', 'delivered', 'cancelled'];
        container.innerHTML = `
            <div class="tabs">
                ${statuses.map((s) => `
                    <button class="tab-btn ${s === 'all' ? 'active' : ''}" data-status="${s}"
                        data-i18n="${s === 'all' ? 'common.all' : 'statuses.' + s}"></button>`).join('')}
            </div>
            ${canEdit ? `<button class="btn btn-primary btn-block" id="add-order-btn" style="margin-bottom:12px;" data-i18n="orders.new_order"></button>` : ''}
            <div id="orders-list" class="card-grid"></div>
        `;

        container.querySelectorAll('.tab-btn').forEach((btn) => {
            btn.addEventListener('click', () => {
                container.querySelectorAll('.tab-btn').forEach((b) => b.classList.remove('active'));
                btn.classList.add('active');
                this.currentStatus = btn.dataset.status;
                this.loadOrders();
            });
        });
        if (canEdit) {
            container.querySelector('#add-order-btn').addEventListener('click', () => this.openForm());
        }

        window.i18n.applyTranslations();
        await this.loadOrders();
    }

    async loadOrders() {
        const listEl = document.getElementById('orders-list');
        window.listStates.loading(listEl, window.ui.t('common.loading'));
        try {
            const query = this.currentStatus !== 'all' ? `?status=${this.currentStatus}` : '';
            const response = await window.api.request(`/orders/orders/${query}`);
            this.orders = response.results || response;

            if (!this.orders.length) {
                window.listStates.empty(listEl, window.ui.t('common.no_data'));
                return;
            }
            listEl.innerHTML = this.orders.map((o) => this.renderCard(o)).join('');
            listEl.querySelectorAll('[data-id]').forEach((card) => {
                card.addEventListener('click', () => {
                    const order = this.orders.find((o) => o.id === Number(card.dataset.id));
                    this.openDetail(order);
                });
            });
            window.i18n.applyTranslations();
        } catch (e) {
            window.listStates.error(listEl, window.ui.t('common.error'), () => this.loadOrders());
        }
    }

    renderCard(o) {
        const danger = o.has_material_shortage || o.payment_status === 'unpaid';
        return `
            <div class="card" data-id="${o.id}" style="cursor:pointer;${danger ? 'border-left:4px solid var(--danger-color);' : ''}">
                <div class="card-title" style="margin-bottom:4px;">
                    <span>#${o.id} ${window.ui.escape(o.client_name)}</span>
                    ${window.ui.orderBadge(o.status)}
                </div>
                <div class="text-sm text-muted">
                    ${window.ui.escape(o.product_name || o.custom_product_name || '-')} — ${window.ui.qty(o.quantity)} ${window.ui.escape(o.unit)}
                </div>
                <div style="display:flex;justify-content:space-between;align-items:center;margin-top:8px;">
                    <div>
                        ${o.has_material_shortage ? `<div class="text-sm text-danger">⚠️ <span data-i18n="orders.material_shortage"></span></div>` : ''}
                        ${o.is_overdue ? `<div class="text-sm text-danger">⏰ <span data-i18n="dashboard.deadline_passed"></span></div>` : ''}
                    </div>
                    ${window.ui.paymentBadge(o.payment_status)}
                </div>
                <div class="text-sm text-muted" style="margin-top:8px;text-align:right;">
                    ${o.deadline ? `<span data-i18n="orders.deadline"></span>: ${window.ui.date(o.deadline)}` : window.ui.date(o.created_at)}
                </div>
            </div>`;
    }

    async openDetail(o) {
        const user = window.currentUser;
        const canManage = user.is_owner || user.is_admin;
        const row = (labelKey, valueHtml) => (!valueHtml ? '' : `
            <div class="list-row" style="cursor:default;">
                <span class="text-sm text-muted" data-i18n="${labelKey}"></span>
                <span class="text-sm font-bold" style="text-align:right;">${valueHtml}</span>
            </div>`);

        const shortages = (o.material_shortages || []).map((s) => `
            <div class="alert-box" style="margin-bottom:8px;">
                ⚠️ ${window.ui.escape(s.material_name)}:
                <span data-i18n="orders.required_materials"></span> ${window.ui.qty(s.required)},
                <span data-i18n="warehouse.quantity"></span> ${window.ui.qty(s.available)}
            </div>`).join('');

        const modal = window.ui.modal('orders.order_details', `
            <div class="card-title">
                <span>#${o.id} ${window.ui.escape(o.client_name)}</span>
                ${window.ui.orderBadge(o.status)}
            </div>
            ${shortages}
            <div class="list-group" style="box-shadow:none;border:1px solid #efeff4;">
                ${row('orders.product', window.ui.escape(o.product_name || o.custom_product_name || '-'))}
                ${row('orders.quantity', `${window.ui.qty(o.quantity)} ${window.ui.escape(o.unit)}`)}
                ${row('orders.deadline', o.deadline ? window.ui.datetime(o.deadline) : '')}
                ${row('orders.worker', window.ui.escape(o.worker_name || ''))}
                ${row('orders.payment_status', window.ui.paymentBadge(o.payment_status))}
                ${user.is_owner ? row('clients.total_amount', window.ui.money(o.total_amount)) : ''}
                ${user.is_owner ? row('clients.paid', window.ui.money(o.paid_amount)) : ''}
                ${user.is_owner && o.total_amount - o.paid_amount > 0 ? row('clients.debt', `<span class="text-danger">${window.ui.money(o.total_amount - o.paid_amount)}</span>`) : ''}
                ${row('orders.comment', window.ui.escape(o.comment || ''))}
            </div>
            ${canManage ? `
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:14px;">
                    ${['new', 'awaiting_material', 'worker_refused'].includes(o.status) ? `
                        <button class="btn btn-primary btn-sm" id="send-worker" data-i18n="orders.send_to_worker"></button>` : ''}
                    ${o.status === 'ready' ? `
                        <button class="btn btn-success btn-sm" id="deliver-order" data-i18n="orders.deliver"></button>` : ''}
                    ${user.is_owner && o.payment_status !== 'paid' ? `
                        <button class="btn btn-success btn-sm" id="add-payment" data-i18n="orders.add_payment"></button>` : ''}
                    ${!['delivered', 'cancelled'].includes(o.status) ? `
                        <button class="btn btn-secondary btn-sm" id="edit-order" data-i18n="common.edit"></button>
                        <button class="btn btn-danger btn-sm" id="cancel-order" data-i18n="common.cancel"></button>` : ''}
                </div>` : ''}
        `);

        const bind = (id, handler) => {
            const el = modal.querySelector(`#${id}`);
            if (el) el.addEventListener('click', handler);
        };
        bind('send-worker', () => { modal.remove(); this.openSendToWorker(o); });
        bind('edit-order', () => { modal.remove(); this.openForm(o); });
        bind('add-payment', () => { modal.remove(); this.openPaymentForm(o); });
        bind('deliver-order', async () => {
            if (!(await window.confirmation.confirm(window.ui.t('orders.deliver_confirm'), window.ui.t('orders.deliver')))) return;
            try {
                await window.api.request(`/orders/orders/${o.id}/deliver/`, { method: 'POST' });
                modal.remove();
                window.toast.success(window.ui.t('common.success'));
                await this.loadOrders();
            } catch (error) {
                window.toast.error(window.ui.errorText(error));
            }
        });
        bind('cancel-order', async () => {
            if (!(await window.confirmation.confirm(window.ui.t('orders.cancel_confirm'), window.ui.t('common.cancel')))) return;
            try {
                await window.api.request(`/orders/orders/${o.id}/cancel/`, { method: 'POST' });
                modal.remove();
                window.toast.success(window.ui.t('common.success'));
                await this.loadOrders();
            } catch (error) {
                window.toast.error(window.ui.errorText(error));
            }
        });
    }

    /** Форма создания/редактирования заказа. */
    async openForm(o = null) {
        const isOwner = window.currentUser.is_owner;
        const [clientsResp, productsResp] = await Promise.all([
            window.api.request('/clients/clients/?is_archived=false'),
            window.api.request('/warehouse/finished-products/?is_archived=false'),
        ]);
        const clients = clientsResp.results || clientsResp;
        const products = productsResp.results || productsResp;

        const modal = window.ui.modal(o ? 'common.edit' : 'orders.new_order', `
            <form id="order-form">
                <div class="form-group"><label data-i18n="orders.client"></label>
                    <select name="client" class="form-control" required>
                        <option value=""></option>
                        ${clients.map((c) => `<option value="${c.id}" ${o?.client === c.id ? 'selected' : ''}>${window.ui.escape(c.name)}</option>`).join('')}
                    </select></div>
                <div class="form-group"><label data-i18n="orders.product"></label>
                    <select name="product" class="form-control">
                        <option value=""></option>
                        ${products.map((p) => `<option value="${p.id}" ${o?.product === p.id ? 'selected' : ''}>${window.ui.escape(p.name)}</option>`).join('')}
                    </select></div>
                <div class="form-group"><label data-i18n="orders.custom_product"></label>
                    <input name="custom_product_name" class="form-control" value="${window.ui.escape(o?.custom_product_name || '')}"></div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                    <div class="form-group"><label data-i18n="orders.quantity"></label>
                        <input name="quantity" type="number" step="0.01" min="0.01" class="form-control" required value="${o?.quantity ?? ''}"></div>
                    <div class="form-group"><label data-i18n="orders.unit"></label>
                        <select name="unit" class="form-control">${window.ui.unitOptions(o?.unit || 'izdelie')}</select></div>
                </div>
                <div class="form-group"><label data-i18n="orders.deadline"></label>
                    <input name="deadline" type="datetime-local" class="form-control" value="${o?.deadline ? o.deadline.slice(0, 16) : ''}"></div>
                ${isOwner ? `
                    <div class="form-group"><label data-i18n="clients.total_amount"></label>
                        <input name="total_amount" type="number" step="0.01" min="0" class="form-control" value="${o?.total_amount ?? 0}"></div>` : ''}
                <div class="form-group"><label data-i18n="orders.comment"></label>
                    <textarea name="comment" class="form-control" rows="2">${window.ui.escape(o?.comment || '')}</textarea></div>
                <button type="submit" class="btn btn-primary btn-block" data-i18n="common.save"></button>
            </form>
        `);

        modal.querySelector('#order-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target));
            if (!data.product) delete data.product;
            if (!data.deadline) delete data.deadline;
            await window.ui.submitGuard(e.target.querySelector('button[type=submit]'), async () => {
                try {
                    if (o) {
                        await window.api.request(`/orders/orders/${o.id}/`, { method: 'PATCH', body: JSON.stringify(data) });
                    } else {
                        await window.api.request('/orders/orders/', { method: 'POST', body: JSON.stringify(data) });
                    }
                    modal.remove();
                    window.toast.success(window.ui.t('common.success'));
                    await this.loadOrders();
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        });
    }

    /** Назначение работника: создаёт задачу через production API. */
    async openSendToWorker(o) {
        const usersResp = await window.api.request('/accounts/users/');
        const users = usersResp.results || usersResp;
        const workers = users.filter((u) => u.role === 'worker' && u.is_active !== false);

        const modal = window.ui.modal('orders.send_to_worker', `
            ${o.has_material_shortage ? `
                <div class="alert-box">⚠️ <span data-i18n="orders.material_shortage"></span></div>` : ''}
            <form id="assign-form">
                <div class="form-group"><label data-i18n="orders.worker"></label>
                    <select name="worker" class="form-control" required>
                        <option value=""></option>
                        ${workers.map((w) => `<option value="${w.id}">${window.ui.escape(w.full_name || w.username)}</option>`).join('')}
                    </select></div>
                <button type="submit" class="btn btn-primary btn-block" data-i18n="orders.send_to_worker"></button>
            </form>
        `);

        modal.querySelector('#assign-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const worker = new FormData(e.target).get('worker');
            await window.ui.submitGuard(e.target.querySelector('button[type=submit]'), async () => {
                try {
                    await window.api.request('/production/tasks/', {
                        method: 'POST',
                        body: JSON.stringify({ order: o.id, worker }),
                    });
                    modal.remove();
                    window.toast.success(window.ui.t('common.success'));
                    await this.loadOrders();
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        });
    }

    /** Приём оплаты по заказу (только owner). */
    openPaymentForm(o) {
        const debt = Math.max(Number(o.total_amount) - Number(o.paid_amount), 0);
        const modal = window.ui.modal('orders.add_payment', `
            <p style="margin-bottom:12px;">
                <span data-i18n="clients.debt"></span>:
                <strong class="text-danger">${window.ui.money(debt)}</strong>
            </p>
            <form id="payment-form">
                <div class="form-group"><label data-i18n="common.amount"></label>
                    <input name="amount" type="number" step="0.01" min="0.01" class="form-control" required value="${debt || ''}"></div>
                <div class="form-group"><label data-i18n="common.payment_method"></label>
                    <select name="payment_method" class="form-control">
                        <option value="cash" data-i18n="common.cash"></option>
                        <option value="card" data-i18n="common.card"></option>
                        <option value="transfer" data-i18n="common.transfer"></option>
                        <option value="other" data-i18n="common.other"></option>
                    </select></div>
                <div class="form-group"><label data-i18n="orders.comment"></label>
                    <textarea name="comment" class="form-control" rows="2"></textarea></div>
                <button type="submit" class="btn btn-success btn-block" data-i18n="common.save"></button>
            </form>
        `);

        modal.querySelector('#payment-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target));
            data.client = o.client;
            data.order = o.id;
            data.payment_date = new Date().toISOString();
            await window.ui.submitGuard(e.target.querySelector('button[type=submit]'), async () => {
                try {
                    await window.api.request('/clients/payments/', { method: 'POST', body: JSON.stringify(data) });
                    modal.remove();
                    window.toast.success(window.ui.t('common.success'));
                    await this.loadOrders();
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        });
    }
}

window.OrdersComponent = new OrdersComponent();
