/**
 * Компонент для управления заказами.
 *
 * Отображает список заказов, позволяет создавать, редактировать и назначать работников.
 * Поддерживает фильтрацию по статусу и клиенту.
 */
class OrdersComponent {
    /**
     * Рендерит страницу заказов.
     *
     * @param {HTMLElement} container - Контейнер для рендеринга
     */
    async render(container) {
        container.innerHTML = `
            <header style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                <h1 data-i18n="orders.title">Буюртмалар</h1>
                <div style="display: flex; gap: 10px;">
                    <select id="order-status-filter" class="form-control" style="width: auto;">
                        <option value="" data-i18n="orders.all_statuses">Барча ҳолатлар</option>
                        <option value="new" data-i18n="statuses.new">Янги</option>
                        <option value="in_progress" data-i18n="statuses.in_progress">Иш жараёнида</option>
                        <option value="ready" data-i18n="statuses.ready">Тайёр</option>
                        <option value="delivered" data-i18n="statuses.delivered">Берилди</option>
                    </select>
                    <button id="add-order-btn" class="btn btn-primary" data-i18n="orders.add_order">Қўшиш</button>
                </div>
            </header>
            
            <div class="card" style="overflow-x: auto;">
                <table style="width: 100%; border-collapse: collapse; text-align: left;">
                    <thead>
                        <tr style="border-bottom: 2px solid #eee;">
                            <th style="padding: 10px;" data-i18n="orders.id">ID</th>
                            <th style="padding: 10px;" data-i18n="orders.client">Мижоз</th>
                            <th style="padding: 10px;" data-i18n="orders.product">Маҳсулот</th>
                            <th style="padding: 10px;" data-i18n="orders.quantity">Миқдор</th>
                            <th style="padding: 10px;" data-i18n="orders.deadline">Муддат</th>
                            <th style="padding: 10px;" data-i18n="orders.status">Ҳолат</th>
                            <th style="padding: 10px;" data-i18n="orders.payment_status">Тўлов</th>
                            <th style="padding: 10px;" data-i18n="common.actions">Амаллар</th>
                        </tr>
                    </thead>
                    <tbody id="orders-list">
                        <tr><td colspan="8" style="padding: 10px; text-align: center;" data-i18n="common.loading">Юкланмоқда...</td></tr>
                    </tbody>
                </table>
            </div>
        `;

        await this.loadOrders(container);
        this.setupEventListeners(container);
    }

    /**
     * Загружает список заказов с сервера.
     *
     * @param {HTMLElement} container - Контейнер
     */
    async loadOrders(container) {
        const listEl = container.querySelector('#orders-list');
        const statusFilter = container.querySelector('#order-status-filter').value;
        window.listStates.tableLoading(listEl, 8);
        
        try {
            let url = '/orders/';
            const params = new URLSearchParams();
            if (statusFilter) params.append('status', statusFilter);
            if (params.toString()) url += '?' + params.toString();
            
            const data = await window.api.request(url);
            
            if (data.results && data.results.length > 0) {
                listEl.innerHTML = data.results.map(o => `
                    <tr style="border-bottom: 1px solid #eee; ${o.is_overdue ? 'background-color: #fff3cd;' : ''}">
                        <td style="padding: 10px;">#${o.id}</td>
                        <td style="padding: 10px;">${o.client_name}</td>
                        <td style="padding: 10px;">${o.product_name || o.product_name}</td>
                        <td style="padding: 10px;">${o.quantity} ${o.unit}</td>
                        <td style="padding: 10px;">${o.deadline}</td>
                        <td style="padding: 10px;">
                            <span class="badge badge-${this.getStatusBadgeClass(o.status)}">
                                ${this.getStatusDisplay(o.status)}
                            </span>
                        </td>
                        <td style="padding: 10px;">
                            <span class="badge badge-${this.getPaymentBadgeClass(o.payment_status)}">
                                ${this.getPaymentDisplay(o.payment_status)}
                            </span>
                        </td>
                        <td style="padding: 10px;">
                            <button class="btn btn-sm btn-info" onclick="window.router.navigate('#orders/${o.id}')">
                                <span data-i18n="common.view">Кўриш</span>
                            </button>
                        </td>
                    </tr>
                `).join('');
            } else {
                window.listStates.tableEmpty(listEl, 8, 'No orders found');
            }
            window.i18n.applyTranslations();
        } catch (e) {
            console.error('Failed to load orders', e);
            window.listStates.tableError(listEl, 8, 'Unable to load orders', () => this.loadOrders(container));
            window.i18n.applyTranslations();
        }
    }

    /**
     * Возвращает класс бейджа для статуса заказа.
     *
     * @param {string} status - Статус заказа
     * @returns {string} Класс CSS
     */
    getStatusBadgeClass(status) {
        const classes = {
            'new': 'primary',
            'awaiting_material': 'warning',
            'sent_to_worker': 'info',
            'accepted_by_worker': 'success',
            'worker_refused': 'danger',
            'in_progress': 'info',
            'awaiting_confirmation': 'warning',
            'ready': 'success',
            'delivered': 'success',
            'cancelled': 'secondary'
        };
        return classes[status] || 'secondary';
    }

    /**
     * Возвращает отображаемое название статуса.
     *
     * @param {string} status - Статус заказа
     * @returns {string} Отображаемое название
     */
    getStatusDisplay(status) {
        if (window.i18n && window.i18n.translate) {
            const key = 'statuses.' + status;
            const translated = window.i18n.translate(key);
            if (translated !== key) return translated;
        }
        const displays = {
            'new': 'Янги',
            'awaiting_material': 'Материал кутилмоқда',
            'sent_to_worker': 'Ишчига юборилган',
            'accepted_by_worker': 'Қабул қилинди',
            'worker_refused': 'Рад этилди',
            'in_progress': 'Иш жараёнида',
            'awaiting_confirmation': 'Тасдиқлаш кутилмоқда',
            'ready': 'Тайёр',
            'delivered': 'Берилди',
            'cancelled': 'Бекор қилинди'
        };
        return displays[status] || status;
    }

    /**
     * Возвращает класс бейджа для статуса оплаты.
     *
     * @param {string} paymentStatus - Статус оплаты
     * @returns {string} Класс CSS
     */
    getPaymentBadgeClass(paymentStatus) {
        const classes = {
            'unpaid': 'danger',
            'partial': 'warning',
            'paid': 'success'
        };
        return classes[paymentStatus] || 'secondary';
    }

    /**
     * Возвращает отображаемое название статуса оплаты.
     *
     * @param {string} paymentStatus - Статус оплаты
     * @returns {string} Отображаемое название
     */
    getPaymentDisplay(paymentStatus) {
        if (window.i18n && window.i18n.translate) {
            const key = 'payment_statuses.' + paymentStatus;
            const translated = window.i18n.translate(key);
            if (translated !== key) return translated;
        }
        const displays = {
            'unpaid': 'Тўланмаган',
            'partial': 'Қисман',
            'paid': 'Тўланган'
        };
        return displays[paymentStatus] || paymentStatus;
    }

    /**
     * Настраивает обработчики событий.
     *
     * @param {HTMLElement} container - Контейнер
     */
    setupEventListeners(container) {
        const filter = container.querySelector('#order-status-filter');
        filter.addEventListener('change', () => this.loadOrders(container));

        const addBtn = container.querySelector('#add-order-btn');
        addBtn.addEventListener('click', () => this.showAddOrderModal(container));
    }

    /**
     * Показывает модальное окно для добавления заказа.
     *
     * @param {HTMLElement} container - Контейнер
     */
    async showAddOrderModal(container) {
        // Загрузка клиентов и продуктов
        let clients = [];
        let products = [];
        
        try {
            clients = await window.api.request('/clients/active/');
            products = await window.api.request('/warehouse/finished-products/');
        } catch (e) {
            console.error('Failed to load data', e);
        }

        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.style.display = 'block';
        modal.innerHTML = `
            <div class="modal-content">
                <div class="modal-header">
                    <h3 data-i18n="orders.add_order">Янги буюртма</h3>
                    <button class="close">&times;</button>
                </div>
                <div class="modal-body">
                    <form id="add-order-form">
                        <div class="form-group">
                            <label data-i18n="orders.client">Мижоз</label>
                            <select name="client" class="form-control" required>
                                <option value="">Танланг...</option>
                                ${clients.map(c => `<option value="${c.id}">${c.name}</option>`).join('')}
                            </select>
                        </div>
                        <div class="form-group">
                            <label data-i18n="orders.product">Маҳсулот</label>
                            <select name="product" class="form-control">
                                <option value="">Танланг...</option>
                                ${products.map(p => `<option value="${p.id}">${p.name}</option>`).join('')}
                            </select>
                        </div>
                        <div class="form-group">
                            <label data-i18n="orders.product_name">Маҳсулот номи (агар рўйхатда йўқ бўлса)</label>
                            <input type="text" name="product_name" class="form-control">
                        </div>
                        <div class="form-group">
                            <label data-i18n="orders.quantity">Миқдор</label>
                            <input type="number" name="quantity" class="form-control" required step="0.001">
                        </div>
                        <div class="form-group">
                            <label data-i18n="orders.unit">Бирлик</label>
                            <select name="unit" class="form-control" required>
                                <option value="sht">Дона</option>
                                <option value="m2">м²</option>
                                <option value="m">м</option>
                                <option value="kg">кг</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label data-i18n="orders.deadline">Муддат</label>
                            <input type="date" name="deadline" class="form-control" required>
                        </div>
                        <div class="form-group">
                            <label data-i18n="orders.material">Материал</label>
                            <input type="text" name="material" class="form-control">
                        </div>
                        <div class="form-group">
                            <label data-i18n="orders.comment">Изоҳ</label>
                            <textarea name="comment" class="form-control" rows="3"></textarea>
                        </div>
                        <button type="submit" class="btn btn-primary" data-i18n="common.save">Сақлаш</button>
                    </form>
                </div>
            </div>
        `;

        document.body.appendChild(modal);
        window.i18n.applyTranslations();

        modal.querySelector('.close').addEventListener('click', () => modal.remove());
        modal.addEventListener('click', (e) => {
            if (e.target === modal) modal.remove();
        });

        modal.querySelector('#add-order-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const data = Object.fromEntries(formData);
            
            try {
                await window.api.request('/orders/', {
                    method: 'POST',
                    body: JSON.stringify(data)
                });
                modal.remove();
                window.toast.success('Order created successfully');
                await this.loadOrders(container);
            } catch (error) {
                window.toast.error(error.data?.detail || 'Failed to add order');
            }
        });
    }
}

window.OrdersComponent = new OrdersComponent();
