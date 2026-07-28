/**
 * Финансы (только owner): аналитика за период, расходы,
 * выплаты работникам, ставки оплаты труда, экспорт.
 */
class FinanceComponent {
    async render(container) {
        document.getElementById('page-title').setAttribute('data-i18n', 'finance.title');
        this.container = container;

        if (!window.currentUser.is_owner) {
            container.innerHTML = `
                <div class="card route-error">
                    <h1>403</h1>
                    <p data-i18n="finance.owner_only"></p>
                </div>`;
            window.i18n.applyTranslations();
            return;
        }

        this.tab = 'analytics';
        container.innerHTML = `
            <div class="tabs">
                <button class="tab-btn active" data-tab="analytics" data-i18n="nav.analytics"></button>
                <button class="tab-btn" data-tab="expenses" data-i18n="finance.expenses"></button>
                <button class="tab-btn" data-tab="payments" data-i18n="nav.worker_payments"></button>
                <button class="tab-btn" data-tab="rates" data-i18n="finance.labor_rates"></button>
            </div>
            <div id="finance-content"></div>
        `;

        container.querySelectorAll('.tab-btn').forEach((btn) => {
            btn.addEventListener('click', () => {
                container.querySelectorAll('.tab-btn').forEach((b) => b.classList.remove('active'));
                btn.classList.add('active');
                this.tab = btn.dataset.tab;
                this.loadTab();
            });
        });

        window.i18n.applyTranslations();
        await this.loadTab();
    }

    loadTab() {
        const map = {
            analytics: () => this.loadAnalytics(),
            expenses: () => this.loadExpenses(),
            payments: () => this.loadPayments(),
            rates: () => this.loadRates(),
        };
        return map[this.tab]();
    }

    get contentEl() {
        return this.container.querySelector('#finance-content');
    }

    async loadAnalytics() {
        const el = this.contentEl;
        window.listStates.loading(el, window.ui.t('common.loading'));
        const period = this.period || 'month';
        try {
            const data = await window.api.request(`/reports/analytics/owner/?period=${period}`);
            const periods = ['today', 'yesterday', 'week', 'month', 'quarter', 'year'];
            const row = (labelKey, value, cls = '') => `
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm text-muted" data-i18n="${labelKey}"></span>
                    <span class="text-sm font-bold ${cls}">${window.ui.money(value)}</span>
                </div>`;

            el.innerHTML = `
                <div class="tabs">
                    ${periods.map((p) => `<button class="tab-btn ${p === period ? 'active' : ''}" data-period="${p}" data-i18n="periods.${p}"></button>`).join('')}
                </div>
                <div class="list-group">
                    ${row('finance.revenue', data.revenue)}
                    ${row('finance.cost_of_goods', data.cost_of_goods)}
                    ${row('finance.gross_profit', data.gross_profit)}
                    ${row('finance.expenses', data.expenses_total)}
                    ${row('finance.salaries', data.salaries)}
                    ${row('finance.taxes', data.taxes)}
                    ${row('finance.losses', data.losses)}
                    ${row('finance.owner_withdrawal', data.owner_withdrawal)}
                    ${row('finance.net_profit', data.net_profit, data.net_profit < 0 ? 'text-danger' : 'text-success')}
                    ${row('finance.cash_in_register', data.cash)}
                    ${row('finance.client_debts', data.client_debts, data.client_debts > 0 ? 'text-danger' : '')}
                    ${row('finance.worker_debts', data.worker_debts)}
                </div>
                <div class="section-title" data-i18n="settings.export"></div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                    <a class="btn btn-secondary btn-sm" href="#" id="export-xlsx">📊 Excel</a>
                    <a class="btn btn-secondary btn-sm" href="#" id="export-pdf">📄 PDF</a>
                </div>`;

            el.querySelectorAll('[data-period]').forEach((btn) => {
                btn.addEventListener('click', () => {
                    this.period = btn.dataset.period;
                    this.loadAnalytics();
                });
            });
            el.querySelector('#export-xlsx').addEventListener('click', (e) => {
                e.preventDefault();
                this.download(`/reports/export/finance/?period=${period}`, 'finance-report.xlsx');
            });
            el.querySelector('#export-pdf').addEventListener('click', (e) => {
                e.preventDefault();
                this.download(`/reports/export/finance/?period=${period}&format=pdf`, 'finance-report.pdf');
            });
            window.i18n.applyTranslations();
        } catch (e) {
            window.listStates.error(el, window.ui.t('common.error'), () => this.loadAnalytics());
        }
    }

    /** Скачивает файл с JWT-заголовком. */
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
        } catch (e) {
            window.toast.error(window.ui.t('common.error'));
        }
    }

    async loadExpenses() {
        const el = this.contentEl;
        window.listStates.loading(el, window.ui.t('common.loading'));
        try {
            const response = await window.api.request('/finance/expenses/');
            const expenses = response.results || response;
            el.innerHTML = `
                <button class="btn btn-primary btn-block" id="add-expense-btn" style="margin-bottom:12px;" data-i18n="finance.add_expense"></button>
                ${expenses.length ? `
                    <div class="list-group">
                        ${expenses.map((x) => `
                            <div class="list-row" style="cursor:default;">
                                <div>
                                    <div style="font-weight:600;font-size:14px;" data-i18n="expense_categories.${x.category}"></div>
                                    <div class="text-sm text-muted">${window.ui.date(x.date)}${x.comment ? ` · ${window.ui.escape(x.comment)}` : ''}</div>
                                </div>
                                <span class="font-bold text-danger">-${window.ui.money(x.amount)}</span>
                            </div>`).join('')}
                    </div>` : `<div class="card list-state" data-i18n="common.no_data"></div>`}`;
            el.querySelector('#add-expense-btn').addEventListener('click', () => this.openExpenseForm());
            window.i18n.applyTranslations();
        } catch (e) {
            window.listStates.error(el, window.ui.t('common.error'), () => this.loadExpenses());
        }
    }

    openExpenseForm() {
        const categories = [
            'rent', 'electricity', 'water', 'transport', 'delivery', 'taxes', 'salary',
            'advance', 'equipment_repair', 'tools', 'consumables', 'material_loss',
            'defect', 'unforeseen', 'owner_withdrawal', 'worker_debt', 'client_refund', 'other',
        ];
        const today = new Date().toISOString().slice(0, 10);
        const modal = window.ui.modal('finance.add_expense', `
            <form id="expense-form">
                <div class="form-group"><label data-i18n="finance.category"></label>
                    <select name="category" class="form-control" required>
                        ${categories.map((c) => `<option value="${c}" data-i18n="expense_categories.${c}"></option>`).join('')}
                    </select></div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                    <div class="form-group"><label data-i18n="common.amount"></label>
                        <input name="amount" type="number" step="0.01" min="0.01" class="form-control" required></div>
                    <div class="form-group"><label data-i18n="common.date"></label>
                        <input name="date" type="date" class="form-control" required value="${today}"></div>
                </div>
                <div class="form-group"><label data-i18n="common.payment_method"></label>
                    <select name="payment_method" class="form-control">
                        <option value="cash" data-i18n="common.cash"></option>
                        <option value="card" data-i18n="common.card"></option>
                        <option value="transfer" data-i18n="common.transfer"></option>
                        <option value="other" data-i18n="common.other"></option>
                    </select></div>
                <div class="form-group"><label data-i18n="warehouse.comment"></label>
                    <textarea name="comment" class="form-control" rows="2"></textarea></div>
                <button type="submit" class="btn btn-primary btn-block" data-i18n="common.save"></button>
            </form>
        `);
        modal.querySelector('#expense-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target));
            await window.ui.submitGuard(e.target.querySelector('button[type=submit]'), async () => {
                try {
                    await window.api.request('/finance/expenses/', { method: 'POST', body: JSON.stringify(data) });
                    window.ui.closeModal(modal);
                    window.toast.success(window.ui.t('common.success'));
                    await this.loadExpenses();
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        });
    }

    async loadPayments() {
        const el = this.contentEl;
        window.listStates.loading(el, window.ui.t('common.loading'));
        try {
            const response = await window.api.request('/finance/worker-payments/');
            const payments = response.results || response;
            el.innerHTML = `
                <button class="btn btn-primary btn-block" id="add-payment-btn" style="margin-bottom:12px;" data-i18n="finance.add_payment"></button>
                ${payments.length ? `
                    <div class="list-group">
                        ${payments.map((p) => `
                            <div class="list-row" style="cursor:default;">
                                <div>
                                    <div style="font-weight:600;font-size:14px;">${window.ui.escape(p.worker_name)}</div>
                                    <div class="text-sm text-muted">
                                        ${window.ui.date(p.payment_date)} · <span data-i18n="payment_types.${p.payment_type}"></span>
                                    </div>
                                </div>
                                <span class="font-bold">${window.ui.money(p.amount)}</span>
                            </div>`).join('')}
                    </div>` : `<div class="card list-state" data-i18n="common.no_data"></div>`}`;
            el.querySelector('#add-payment-btn').addEventListener('click', () => this.openPaymentForm());
            window.i18n.applyTranslations();
        } catch (e) {
            window.listStates.error(el, window.ui.t('common.error'), () => this.loadPayments());
        }
    }

    async openPaymentForm() {
        const usersResp = await window.api.request('/accounts/users/');
        const users = usersResp.results || usersResp;
        const workers = users.filter((u) => u.role === 'worker');
        const today = new Date().toISOString().slice(0, 10);

        const modal = window.ui.modal('finance.add_payment', `
            <form id="worker-payment-form">
                <div class="form-group"><label data-i18n="finance.worker"></label>
                    <select name="worker" class="form-control" required>
                        <option value="" data-i18n="common.select"></option>
                        ${workers.map((w) => `<option value="${w.id}">${window.ui.escape(w.full_name || w.username)}</option>`).join('')}
                    </select></div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                    <div class="form-group"><label data-i18n="common.amount"></label>
                        <input name="amount" type="number" step="0.01" min="0.01" class="form-control" required></div>
                    <div class="form-group"><label data-i18n="common.date"></label>
                        <input name="payment_date" type="date" class="form-control" required value="${today}"></div>
                </div>
                <div class="form-group"><label data-i18n="finance.payment_type"></label>
                    <select name="payment_type" class="form-control">
                        <option value="salary" data-i18n="payment_types.salary"></option>
                        <option value="advance" data-i18n="payment_types.advance"></option>
                        <option value="bonus" data-i18n="payment_types.bonus"></option>
                        <option value="other" data-i18n="payment_types.other"></option>
                    </select></div>
                <div class="form-group"><label data-i18n="warehouse.comment"></label>
                    <textarea name="comment" class="form-control" rows="2"></textarea></div>
                <button type="submit" class="btn btn-primary btn-block" data-i18n="common.save"></button>
            </form>
        `);
        modal.querySelector('#worker-payment-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target));
            await window.ui.submitGuard(e.target.querySelector('button[type=submit]'), async () => {
                try {
                    await window.api.request('/finance/worker-payments/', { method: 'POST', body: JSON.stringify(data) });
                    window.ui.closeModal(modal);
                    window.toast.success(window.ui.t('common.success'));
                    await this.loadPayments();
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        });
    }

    async loadRates() {
        const el = this.contentEl;
        window.listStates.loading(el, window.ui.t('common.loading'));
        try {
            const response = await window.api.request('/finance/labor-rates/');
            const rates = response.results || response;
            el.innerHTML = `
                <button class="btn btn-primary btn-block" id="add-rate-btn" style="margin-bottom:12px;" data-i18n="finance.add_rate"></button>
                ${rates.length ? `
                    <div class="list-group">
                        ${rates.map((r) => `
                            <div class="list-row" style="cursor:default;">
                                <div>
                                    <div style="font-weight:600;font-size:14px;">${window.ui.escape(r.product_name)}</div>
                                    <div class="text-sm text-muted" data-i18n="operations.${r.operation}"></div>
                                </div>
                                <span class="font-bold">${window.ui.money(r.rate_per_unit)} / <span data-i18n="units.${r.unit}"></span></span>
                            </div>`).join('')}
                    </div>` : `<div class="card list-state" data-i18n="common.no_data"></div>`}`;
            el.querySelector('#add-rate-btn').addEventListener('click', () => this.openRateForm());
            window.i18n.applyTranslations();
        } catch (e) {
            window.listStates.error(el, window.ui.t('common.error'), () => this.loadRates());
        }
    }

    async openRateForm() {
        const productsResp = await window.api.request('/warehouse/finished-products/?is_archived=false');
        const products = productsResp.results || productsResp;
        const operations = ['cutting', 'polishing', 'mounting', 'packing', 'other'];

        const modal = window.ui.modal('finance.add_rate', `
            <form id="rate-form">
                <div class="form-group"><label data-i18n="finance.product"></label>
                    <select name="product" class="form-control" required>
                        <option value="" data-i18n="common.select"></option>
                        ${products.map((p) => `<option value="${p.id}">${window.ui.escape(p.name)}</option>`).join('')}
                    </select></div>
                <div class="form-group"><label data-i18n="finance.operation"></label>
                    <select name="operation" class="form-control">
                        ${operations.map((o) => `<option value="${o}" data-i18n="operations.${o}"></option>`).join('')}
                    </select></div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                    <div class="form-group"><label data-i18n="finance.rate"></label>
                        <input name="rate_per_unit" type="number" step="0.01" min="0.01" class="form-control" required></div>
                    <div class="form-group"><label data-i18n="warehouse.unit"></label>
                        <select name="unit" class="form-control">${window.ui.unitOptions('sht')}</select></div>
                </div>
                <button type="submit" class="btn btn-primary btn-block" data-i18n="common.save"></button>
            </form>
        `);
        modal.querySelector('#rate-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const data = Object.fromEntries(new FormData(e.target));
            await window.ui.submitGuard(e.target.querySelector('button[type=submit]'), async () => {
                try {
                    await window.api.request('/finance/labor-rates/', { method: 'POST', body: JSON.stringify(data) });
                    window.ui.closeModal(modal);
                    window.toast.success(window.ui.t('common.success'));
                    await this.loadRates();
                } catch (error) {
                    window.toast.error(window.ui.errorText(error));
                }
            });
        });
    }
}

window.FinanceComponent = new FinanceComponent();
