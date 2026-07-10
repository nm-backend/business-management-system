/**
 * Компонент для управления финансами.
 *
 * Отображает расходы, выплаты работникам и ставки оплаты труда.
 * Доступен только владельцу (owner).
 */
class FinanceComponent {
    /**
     * Рендерит страницу финансов.
     *
     * @param {HTMLElement} container - Контейнер для рендеринга
     */
    async render(container) {
        // Проверка прав доступа
        const user = await window.api.getMe();
        if (!user.is_owner) {
            container.innerHTML = `
                <div class="card" style="padding: 40px; text-align: center;">
                    <h2 data-i18n="finance.access_denied">Кириш таъқиланди</h2>
                    <p data-i18n="finance.owner_only">Бу саҳифа фақат эгаси учун</p>
                </div>
            `;
            window.i18n.applyTranslations();
            return;
        }

        container.innerHTML = `
            <header style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                <h1 data-i18n="finance.title">Молия</h1>
                <div style="display: flex; gap: 10px;">
                    <select id="finance-tab" class="form-control" style="width: auto;">
                        <option value="expenses" data-i18n="finance.expenses">Харажатлар</option>
                        <option value="payments" data-i18n="finance.worker_payments">Ишчи тўловлари</option>
                        <option value="rates" data-i18n="finance.labor_rates">Иш ҳақи ставкалари</option>
                    </select>
                </div>
            </header>
            
            <div id="finance-content">
                <!-- Содержимое загружается динамически -->
            </div>
        `;

        await this.loadExpenses(container);
        this.setupEventListeners(container);
    }

    /**
     * Загружает список расходов.
     *
     * @param {HTMLElement} container - Контейнер
     */
    async loadExpenses(container) {
        const contentEl = container.querySelector('#finance-content');
        
        try {
            const data = await window.api.request('/api/v1/finance/expenses/');
            
            if (data && data.length > 0) {
                contentEl.innerHTML = `
                    <div style="display: flex; justify-content: flex-end; margin-bottom: 15px;">
                        <button id="add-expense-btn" class="btn btn-primary" data-i18n="finance.add_expense">Харажат қўшиш</button>
                    </div>
                    <div class="card" style="overflow-x: auto;">
                        <table style="width: 100%; border-collapse: collapse; text-align: left;">
                            <thead>
                                <tr style="border-bottom: 2px solid #eee;">
                                    <th style="padding: 10px;" data-i18n="finance.category">Категория</th>
                                    <th style="padding: 10px;" data-i18n="finance.amount">Сумма</th>
                                    <th style="padding: 10px;" data-i18n="finance.date">Сана</th>
                                    <th style="padding: 10px;" data-i18n="finance.comment">Изоҳ</th>
                                    <th style="padding: 10px;" data-i18n="common.actions">Амаллар</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${data.map(e => `
                                    <tr style="border-bottom: 1px solid #eee;">
                                        <td style="padding: 10px;">${this.getCategoryDisplay(e.category)}</td>
                                        <td style="padding: 10px; font-weight: bold;">${e.amount}</td>
                                        <td style="padding: 10px;">${e.date}</td>
                                        <td style="padding: 10px;">${e.comment || '-'}</td>
                                        <td style="padding: 10px;">
                                            <button class="btn btn-sm btn-info" onclick="window.router.navigate('#finance/expenses/${e.id}')">
                                                <span data-i18n="common.view">Кўриш</span>
                                            </button>
                                        </td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                `;
            } else {
                contentEl.innerHTML = `
                    <div style="display: flex; justify-content: flex-end; margin-bottom: 15px;">
                        <button id="add-expense-btn" class="btn btn-primary" data-i18n="finance.add_expense">Харажат қўшиш</button>
                    </div>
                    <div class="card" style="padding: 20px; text-align: center;" data-i18n="common.no_data">Маълумот йўқ</div>
                `;
            }
            window.i18n.applyTranslations();
            
            // Добавляем обработчик для кнопки добавления
            const addBtn = contentEl.querySelector('#add-expense-btn');
            if (addBtn) {
                addBtn.addEventListener('click', () => this.showAddExpenseModal(container));
            }
        } catch (e) {
            console.error('Failed to load expenses', e);
            contentEl.innerHTML = `<div class="card" style="padding: 20px; text-align: center; color: red;" data-i18n="common.error">Хатолик</div>`;
            window.i18n.applyTranslations();
        }
    }

    /**
     * Загружает список выплат работникам.
     *
     * @param {HTMLElement} container - Контейнер
     */
    async loadPayments(container) {
        const contentEl = container.querySelector('#finance-content');
        
        try {
            const data = await window.api.request('/api/v1/finance/worker-payments/');
            
            if (data && data.length > 0) {
                contentEl.innerHTML = `
                    <div style="display: flex; justify-content: flex-end; margin-bottom: 15px;">
                        <button id="add-payment-btn" class="btn btn-primary" data-i18n="finance.add_payment">Тўлов қўшиш</button>
                    </div>
                    <div class="card" style="overflow-x: auto;">
                        <table style="width: 100%; border-collapse: collapse; text-align: left;">
                            <thead>
                                <tr style="border-bottom: 2px solid #eee;">
                                    <th style="padding: 10px;" data-i18n="finance.worker">Ишчи</th>
                                    <th style="padding: 10px;" data-i18n="finance.amount">Сумма</th>
                                    <th style="padding: 10px;" data-i18n="finance.payment_date">Тўлов санаси</th>
                                    <th style="padding: 10px;" data-i18n="finance.payment_type">Тўлов тури</th>
                                    <th style="padding: 10px;" data-i18n="common.actions">Амаллар</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${data.map(p => `
                                    <tr style="border-bottom: 1px solid #eee;">
                                        <td style="padding: 10px;">${p.worker_name}</td>
                                        <td style="padding: 10px; font-weight: bold;">${p.amount}</td>
                                        <td style="padding: 10px;">${p.payment_date}</td>
                                        <td style="padding: 10px;">${this.getPaymentTypeDisplay(p.payment_type)}</td>
                                        <td style="padding: 10px;">
                                            <button class="btn btn-sm btn-info" onclick="window.router.navigate('#finance/payments/${p.id}')">
                                                <span data-i18n="common.view">Кўриш</span>
                                            </button>
                                        </td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                `;
            } else {
                contentEl.innerHTML = `
                    <div style="display: flex; justify-content: flex-end; margin-bottom: 15px;">
                        <button id="add-payment-btn" class="btn btn-primary" data-i18n="finance.add_payment">Тўлов қўшиш</button>
                    </div>
                    <div class="card" style="padding: 20px; text-align: center;" data-i18n="common.no_data">Маълумот йўқ</div>
                `;
            }
            window.i18n.applyTranslations();
            
            const addBtn = contentEl.querySelector('#add-payment-btn');
            if (addBtn) {
                addBtn.addEventListener('click', () => this.showAddPaymentModal(container));
            }
        } catch (e) {
            console.error('Failed to load payments', e);
            contentEl.innerHTML = `<div class="card" style="padding: 20px; text-align: center; color: red;" data-i18n="common.error">Хатолик</div>`;
            window.i18n.applyTranslations();
        }
    }

    /**
     * Загружает список ставок оплаты труда.
     *
     * @param {HTMLElement} container - Контейнер
     */
    async loadRates(container) {
        const contentEl = container.querySelector('#finance-content');
        
        try {
            const data = await window.api.request('/api/v1/finance/labor-rates/');
            
            if (data && data.length > 0) {
                contentEl.innerHTML = `
                    <div style="display: flex; justify-content: flex-end; margin-bottom: 15px;">
                        <button id="add-rate-btn" class="btn btn-primary" data-i18n="finance.add_rate">Ставка қўшиш</button>
                    </div>
                    <div class="card" style="overflow-x: auto;">
                        <table style="width: 100%; border-collapse: collapse; text-align: left;">
                            <thead>
                                <tr style="border-bottom: 2px solid #eee;">
                                    <th style="padding: 10px;" data-i18n="finance.product">Маҳсулот</th>
                                    <th style="padding: 10px;" data-i18n="finance.operation">Амалиёт</th>
                                    <th style="padding: 10px;" data-i18n="finance.rate">Ставка</th>
                                    <th style="padding: 10px;" data-i18n="finance.unit">Бирлик</th>
                                    <th style="padding: 10px;" data-i18n="common.actions">Амаллар</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${data.map(r => `
                                    <tr style="border-bottom: 1px solid #eee;">
                                        <td style="padding: 10px;">${r.product_name}</td>
                                        <td style="padding: 10px;">${this.getOperationDisplay(r.operation)}</td>
                                        <td style="padding: 10px; font-weight: bold;">${r.rate_per_unit}</td>
                                        <td style="padding: 10px;">${r.unit}</td>
                                        <td style="padding: 10px;">
                                            <button class="btn btn-sm btn-info" onclick="window.router.navigate('#finance/rates/${r.id}')">
                                                <span data-i18n="common.view">Кўриш</span>
                                            </button>
                                        </td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                `;
            } else {
                contentEl.innerHTML = `
                    <div style="display: flex; justify-content: flex-end; margin-bottom: 15px;">
                        <button id="add-rate-btn" class="btn btn-primary" data-i18n="finance.add_rate">Ставка қўшиш</button>
                    </div>
                    <div class="card" style="padding: 20px; text-align: center;" data-i18n="common.no_data">Маълумот йўқ</div>
                `;
            }
            window.i18n.applyTranslations();
            
            const addBtn = contentEl.querySelector('#add-rate-btn');
            if (addBtn) {
                addBtn.addEventListener('click', () => this.showAddRateModal(container));
            }
        } catch (e) {
            console.error('Failed to load rates', e);
            contentEl.innerHTML = `<div class="card" style="padding: 20px; text-align: center; color: red;" data-i18n="common.error">Хатолик</div>`;
            window.i18n.applyTranslations();
        }
    }

    /**
     * Возвращает отображаемое название категории расхода.
     *
     * @param {string} category - Категория
     * @returns {string} Отображаемое название
     */
    getCategoryDisplay(category) {
        const displays = {
            'rent': 'Ижара',
            'electricity': 'Электр энергия',
            'water': 'Сув',
            'transport': 'Транспорт',
            'delivery': 'Етказиб бериш',
            'taxes': 'Солиқлар',
            'salary': 'Ишчилар иш ҳақи',
            'advance': 'Ишчиларга аванс',
            'equipment_repair': 'Ускуна таъмири',
            'tools': 'Асбоб сотиб олиш',
            'consumables': 'Сарфлаш материаллари',
            'material_loss': 'Материал йўқотиш',
            'defect': 'Брак',
            'unforeseen': 'Кутилмаган харажатлар',
            'owner_withdrawal': 'Эгасининг шахсий чиқими',
            'worker_debt': 'Ишчилар қарзлари',
            'client_refund': 'Мижозларга қайтариш',
            'other': 'Бошқа'
        };
        return displays[category] || category;
    }

    /**
     * Возвращает отображаемое название типа выплаты.
     *
     * @param {string} paymentType - Тип выплаты
     * @returns {string} Отображаемое название
     */
    getPaymentTypeDisplay(paymentType) {
        const displays = {
            'salary': 'Иш ҳақи',
            'advance': 'Аванс',
            'bonus': 'Мукофот',
            'other': 'Бошқа'
        };
        return displays[paymentType] || paymentType;
    }

    /**
     * Возвращает отображаемое название операции.
     *
     * @param {string} operation - Операция
     * @returns {string} Отображаемое название
     */
    getOperationDisplay(operation) {
        const displays = {
            'cutting': 'Кесиш',
            'polishing': 'Сийлаш',
            'mounting': 'Монтаж',
            'packing': 'Қутлаш',
            'other': 'Бошқа'
        };
        return displays[operation] || operation;
    }

    /**
     * Настраивает обработчики событий.
     *
     * @param {HTMLElement} container - Контейнер
     */
    setupEventListeners(container) {
        const tab = container.querySelector('#finance-tab');
        tab.addEventListener('change', (e) => {
            if (e.target.value === 'expenses') {
                this.loadExpenses(container);
            } else if (e.target.value === 'payments') {
                this.loadPayments(container);
            } else {
                this.loadRates(container);
            }
        });
    }

    /**
     * Показывает модальное окно для добавления расхода.
     *
     * @param {HTMLElement} container - Контейнер
     */
    async showAddExpenseModal(container) {
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.style.display = 'block';
        modal.innerHTML = `
            <div class="modal-content">
                <div class="modal-header">
                    <h3 data-i18n="finance.add_expense">Янги харажат</h3>
                    <button class="close">&times;</button>
                </div>
                <div class="modal-body">
                    <form id="add-expense-form">
                        <div class="form-group">
                            <label data-i18n="finance.category">Категория</label>
                            <select name="category" class="form-control" required>
                                <option value="rent">Ижара</option>
                                <option value="electricity">Электр энергия</option>
                                <option value="water">Сув</option>
                                <option value="transport">Транспорт</option>
                                <option value="delivery">Етказиб бериш</option>
                                <option value="taxes">Солиқлар</option>
                                <option value="salary">Ишчилар иш ҳақи</option>
                                <option value="advance">Ишчиларга аванс</option>
                                <option value="equipment_repair">Ускуна таъмири</option>
                                <option value="tools">Асбоб сотиб олиш</option>
                                <option value="consumables">Сарфлаш материаллари</option>
                                <option value="material_loss">Материал йўқотиш</option>
                                <option value="defect">Брак</option>
                                <option value="unforeseen">Кутилмаган харажатлар</option>
                                <option value="owner_withdrawal">Эгасининг шахсий чиқими</option>
                                <option value="worker_debt">Ишчилар қарзлари</option>
                                <option value="client_refund">Мижозларга қайтариш</option>
                                <option value="other">Бошқа</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label data-i18n="finance.amount">Сумма</label>
                            <input type="number" name="amount" class="form-control" required step="0.01">
                        </div>
                        <div class="form-group">
                            <label data-i18n="finance.date">Сана</label>
                            <input type="date" name="date" class="form-control" required>
                        </div>
                        <div class="form-group">
                            <label data-i18n="finance.payment_method">Тўлов усули</label>
                            <select name="payment_method" class="form-control">
                                <option value="cash">Нақд</option>
                                <option value="card">Карта</option>
                                <option value="transfer">Ўтказма</option>
                                <option value="other">Бошқа</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label data-i18n="finance.comment">Изоҳ</label>
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

        modal.querySelector('#add-expense-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const data = Object.fromEntries(formData);
            
            try {
                await window.api.request('/api/v1/finance/expenses/', {
                    method: 'POST',
                    body: JSON.stringify(data)
                });
                modal.remove();
                await this.loadExpenses(container);
            } catch (error) {
                alert('Error: ' + (error.data?.detail || 'Failed to add expense'));
            }
        });
    }

    /**
     * Показывает модальное окно для добавления выплаты.
     *
     * @param {HTMLElement} container - Контейнер
     */
    async showAddPaymentModal(container) {
        // Загрузка работников
        let workers = [];
        try {
            workers = await window.api.request('/api/v1/accounts/users/');
            workers = workers.filter(w => w.role === 'worker');
        } catch (e) {
            console.error('Failed to load workers', e);
        }

        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.style.display = 'block';
        modal.innerHTML = `
            <div class="modal-content">
                <div class="modal-header">
                    <h3 data-i18n="finance.add_payment">Янги тўлов</h3>
                    <button class="close">&times;</button>
                </div>
                <div class="modal-body">
                    <form id="add-payment-form">
                        <div class="form-group">
                            <label data-i18n="finance.worker">Ишчи</label>
                            <select name="worker" class="form-control" required>
                                <option value="">Танланг...</option>
                                ${workers.map(w => `<option value="${w.id}">${w.username} (${w.full_name || ''})</option>`).join('')}
                            </select>
                        </div>
                        <div class="form-group">
                            <label data-i18n="finance.amount">Сумма</label>
                            <input type="number" name="amount" class="form-control" required step="0.01">
                        </div>
                        <div class="form-group">
                            <label data-i18n="finance.payment_date">Тўлов санаси</label>
                            <input type="date" name="payment_date" class="form-control" required>
                        </div>
                        <div class="form-group">
                            <label data-i18n="finance.payment_type">Тўлов тури</label>
                            <select name="payment_type" class="form-control">
                                <option value="salary">Иш ҳақи</option>
                                <option value="advance">Аванс</option>
                                <option value="bonus">Мукофот</option>
                                <option value="other">Бошқа</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label data-i18n="finance.comment">Изоҳ</label>
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

        modal.querySelector('#add-payment-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const data = Object.fromEntries(formData);
            
            try {
                await window.api.request('/api/v1/finance/worker-payments/', {
                    method: 'POST',
                    body: JSON.stringify(data)
                });
                modal.remove();
                await this.loadPayments(container);
            } catch (error) {
                alert('Error: ' + (error.data?.detail || 'Failed to add payment'));
            }
        });
    }

    /**
     * Показывает модальное окно для добавления ставки.
     *
     * @param {HTMLElement} container - Контейнер
     */
    async showAddRateModal(container) {
        // Загрузка продуктов
        let products = [];
        try {
            products = await window.api.request('/api/v1/warehouse/finished-products/');
        } catch (e) {
            console.error('Failed to load products', e);
        }

        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.style.display = 'block';
        modal.innerHTML = `
            <div class="modal-content">
                <div class="modal-header">
                    <h3 data-i18n="finance.add_rate">Янги ставка</h3>
                    <button class="close">&times;</button>
                </div>
                <div class="modal-body">
                    <form id="add-rate-form">
                        <div class="form-group">
                            <label data-i18n="finance.product">Маҳсулот</label>
                            <select name="product" class="form-control" required>
                                <option value="">Танланг...</option>
                                ${products.map(p => `<option value="${p.id}">${p.name}</option>`).join('')}
                            </select>
                        </div>
                        <div class="form-group">
                            <label data-i18n="finance.operation">Амалиёт</label>
                            <select name="operation" class="form-control" required>
                                <option value="cutting">Кесиш</option>
                                <option value="polishing">Сийлаш</option>
                                <option value="mounting">Монтаж</option>
                                <option value="packing">Қутлаш</option>
                                <option value="other">Бошқа</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label data-i18n="finance.rate">Ставка</label>
                            <input type="number" name="rate_per_unit" class="form-control" required step="0.01">
                        </div>
                        <div class="form-group">
                            <label data-i18n="finance.unit">Бирлик</label>
                            <select name="unit" class="form-control" required>
                                <option value="sht">Дона</option>
                                <option value="m2">м²</option>
                                <option value="m">м</option>
                                <option value="kg">кг</option>
                            </select>
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

        modal.querySelector('#add-rate-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const data = Object.fromEntries(formData);
            
            try {
                await window.api.request('/api/v1/finance/labor-rates/', {
                    method: 'POST',
                    body: JSON.stringify(data)
                });
                modal.remove();
                await this.loadRates(container);
            } catch (error) {
                alert('Error: ' + (error.data?.detail || 'Failed to add rate'));
            }
        });
    }
}
