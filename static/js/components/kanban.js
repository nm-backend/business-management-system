/**
 * Kanban-доска для заказов с Drag & Drop между статусами.
 * Использует HTML5 Drag & Drop API + CSS анимации.
 */
class KanbanComponent {
    constructor() {
        this.orders = [];
        this.draggedId = null;
    }

    async render(container) {
        // Убираем data-i18n, иначе applyTranslations() из роутера перезапишет
        // наш заголовок переводом с ПРОШЛОЙ страницы (например, после финансов
        // на kanban висел «Молиявий таҳлил» вместо «Kanban»).
        const title = document.getElementById('page-title');
        title.removeAttribute('data-i18n');
        title.textContent = '🔄 ' + window.ui.t('orders.view_kanban');
        this.container = container;
        await this.loadOrders();
    }

    /** Статусы для колонок Kanban (только активные, не финальные). */
    get columns() {
        return [
            { status: 'new', labelKey: 'statuses.new', icon: '📋' },
            { status: 'awaiting_material', labelKey: 'statuses.awaiting_material', icon: '📦' },
            { status: 'sent_to_worker', labelKey: 'statuses.sent_to_worker', icon: '📨' },
            { status: 'accepted', labelKey: 'statuses.accepted', icon: '✅' },
            { status: 'in_progress', labelKey: 'statuses.in_progress', icon: '🛠️' },
            { status: 'awaiting_confirmation', labelKey: 'statuses.awaiting_confirmation', icon: '⏳' },
            { status: 'ready', labelKey: 'statuses.ready', icon: '🎯' },
            { status: 'delivered', labelKey: 'statuses.delivered', icon: '✓' },
        ];
    }

    async loadOrders() {
        // Пользователь мог уйти со страницы, пока шёл запрос (в т.ч. в 300-мс
        // таймере после move): контейнера больше нет, рисовать некуда.
        if (window.listStates.gone(this.container)) return;
        try {
            const response = await window.api.request('/orders/orders/?ordering=-created_at');
            this.orders = response.results || response;
        } catch (e) {
            window.listStates.error(this.container, window.ui.t('common.error'), () => this.loadOrders());
            return;
        }
        this.renderBoard();
    }

    renderBoard() {
        this.container.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                <div class="tabs" style="margin-bottom:0;" role="tablist" aria-label="Orders view switch">
                    <a class="tab-btn" href="#/orders" style="text-decoration:none;" role="tab" aria-selected="false" data-i18n="orders.view_list"></a>
                    <span class="tab-btn active" role="tab" aria-selected="true" data-i18n="orders.view_kanban"></span>
                </div>
                <button class="btn btn-sm btn-primary" id="kanban-refresh" style="width:auto;padding:8px 14px;" data-i18n="common.retry">🔄</button>
            </div>
            <div class="kanban-board" id="kanban-board"></div>
        `;

        const board = this.container.querySelector('#kanban-board');
        this.columns.forEach((col) => {
            const colOrders = this.orders.filter((o) => o.status === col.status);
            const label = window.ui.t(col.labelKey) || col.status;
            board.appendChild(this.createColumn(col.status, label, col.icon, colOrders));
        });

        this.container.querySelector('#kanban-refresh')?.addEventListener('click', () => this.loadOrders());
        window.i18n.applyTranslations();
    }

    createColumn(status, label, icon, orders) {
        const col = document.createElement('div');
        col.className = 'kanban-column';
        col.dataset.status = status;

        // Header
        const header = document.createElement('div');
        header.className = 'kanban-header';
        header.innerHTML = `
            <span>${icon} ${window.ui.escape(label)}</span>
            <span class="kanban-count">${orders.length}</span>
        `;
        col.appendChild(header);

        // Body (drop zone)
        const body = document.createElement('div');
        body.className = 'kanban-body';
        body.dataset.status = status;

        body.addEventListener('dragover', (e) => {
            e.preventDefault();
            body.classList.add('drag-over');
        });
        body.addEventListener('dragleave', () => {
            body.classList.remove('drag-over');
        });
        body.addEventListener('drop', (e) => {
            e.preventDefault();
            body.classList.remove('drag-over');
            const orderId = e.dataTransfer.getData('text/plain');
            if (orderId) this.moveOrder(orderId, status);
        });

        // Cards
        orders.forEach((o) => {
            const card = this.createCard(o);
            body.appendChild(card);
        });

        col.appendChild(body);
        return col;
    }

    createCard(o) {
        const user = window.currentUser || {};
        // Перетаскивать заказ между статусами может только owner/admin:
        // manager видит доску только на чтение (двигать заказы нельзя).
        const canDrag = !!(user.is_owner || user.is_admin);
        const card = document.createElement('div');
        card.className = 'kanban-card';
        card.draggable = canDrag;
        card.setAttribute('role', 'button');
        card.setAttribute('tabindex', '0');
        card.dataset.id = o.id;

        if (o.has_material_shortage || o.payment_status === 'unpaid') {
            card.classList.add('danger');
        }
        if (o.is_overdue) {
            card.classList.add('overdue');
        }

        // Drag events
        card.addEventListener('dragstart', (e) => {
            if (!canDrag) return;
            e.dataTransfer.setData('text/plain', String(o.id));
            e.dataTransfer.effectAllowed = 'move';
            this.draggedId = o.id;
            setTimeout(() => card.classList.add('dragging'), 0);
        });
        card.addEventListener('dragend', () => {
            card.classList.remove('dragging');
            this.draggedId = null;
        });

        // Click to open detail
        card.addEventListener('click', (e) => {
            if (this.draggedId) return;
            this.openOrderDetail(o);
        });
        card.addEventListener('keydown', (e) => {
            if (this.draggedId) return;
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                this.openOrderDetail(o);
            }
        });

        // Content
        const warnings = [];
        if (o.has_material_shortage) warnings.push(`⚠️ ${window.ui.t('orders.material_shortage')}`);
        if (o.payment_status === 'unpaid') warnings.push(`💰 ${window.ui.t('payment_statuses.unpaid')}`);
        if (o.is_overdue) warnings.push(`⏰ ${window.ui.t('dashboard.deadline_passed')}`);

        card.innerHTML = `
            <div class="kanban-card-id">#${o.id}</div>
            <div class="kanban-card-client">${window.ui.escape(o.client_name || '—')}</div>
            <div class="kanban-card-product">${window.ui.escape(o.product_name || o.custom_product_name || '—')} · ${window.ui.qty(o.quantity)}</div>
            <div class="kanban-card-meta">
                <span>${o.deadline ? window.ui.date(o.deadline) : ''}</span>
                ${window.ui.paymentBadge(o.payment_status)}
            </div>
            ${warnings.length ? `<div class="kanban-card-warning">${warnings[0]}</div>` : ''}
        `;

        return card;
    }

    async moveOrder(orderId, newStatus) {
        const order = this.orders.find((o) => o.id === Number(orderId));
        if (!order || order.status === newStatus) return;
        if (['delivered', 'cancelled'].includes(order.status)) return;

        const validTransitions = {
            'new': ['awaiting_material', 'sent_to_worker', 'cancelled'],
            'awaiting_material': ['new', 'sent_to_worker', 'cancelled'],
            'sent_to_worker': ['accepted', 'worker_refused', 'cancelled'],
            'accepted': ['in_progress', 'worker_refused', 'cancelled'],
            'worker_refused': ['new', 'sent_to_worker'],
            'in_progress': ['awaiting_confirmation', 'cancelled'],
            'awaiting_confirmation': ['ready', 'cancelled'],
            'ready': ['delivered', 'cancelled'],
            'delivered': [],
            'cancelled': [],
        };

        const allowed = validTransitions[order.status] || [];
        if (!allowed.includes(newStatus)) {
            window.toast.error(window.ui.t('orders.cannot_move', {
                from: window.ui.t('statuses.' + order.status),
                to: window.ui.t('statuses.' + newStatus),
            }));
            this.loadOrders();
            return;
        }

        // Optimistic update
        const oldStatus = order.status;
        order.status = newStatus;

        try {
            if (newStatus === 'delivered') {
                await window.api.request(`/orders/orders/${orderId}/deliver/`, { method: 'POST' });
            } else if (newStatus === 'cancelled') {
                await window.api.request(`/orders/orders/${orderId}/cancel/`, { method: 'POST' });
            } else {
                await window.api.request(`/orders/orders/${orderId}/transition/`, {
                    method: 'PATCH',
                    body: JSON.stringify({ status: newStatus }),
                });
            }

            // Анимация drop
            const cards = this.container.querySelectorAll(`.kanban-card[data-id="${orderId}"]`);
            cards.forEach((c) => c.classList.add('dropped'));

            window.toast.success(`#${orderId} → ${window.ui.t('statuses.' + newStatus)}`);
            setTimeout(() => this.loadOrders(), 300);
        } catch (error) {
            order.status = oldStatus; // Revert
            window.toast.error(window.ui.errorText(error));
            this.loadOrders();
        }
    }

    openOrderDetail(o) {
        // Перенаправляем на страницу заказа с деталями
        window.router.navigate(`/orders?focus=${o.id}`);
    }
}

window.KanbanComponent = new KanbanComponent();
