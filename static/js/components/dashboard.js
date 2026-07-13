/**
 * Дашборд: у каждой роли своя главная.
 * Owner - финансовая аналитика, Admin - операционные показатели без денег,
 * Worker - задачи на сегодня и заработок.
 */
class DashboardComponent {
    async render(container) {
        document.getElementById('page-title').setAttribute('data-i18n', 'nav.dashboard');
        window.i18n.applyTranslations();

        const user = window.currentUser;
        if (user.is_owner) await this.renderOwner(container);
        else if (user.is_admin) await this.renderAdmin(container);
        else await this.renderWorker(container);
        window.i18n.applyTranslations();
    }

    async renderOwner(container) {
        const period = this.period || 'month';
        const data = await window.api.request(`/reports/analytics/owner/?period=${period}`);
        const t = (k) => window.ui.t(k);
        const periods = ['today', 'yesterday', 'week', 'month', 'quarter', 'year'];

        container.innerHTML = `
            <div class="tabs">
                ${periods.map((p) => `
                    <button class="tab-btn ${p === period ? 'active' : ''}" data-period="${p}" data-i18n="periods.${p}"></button>
                `).join('')}
            </div>

            <div class="card hero-card" style="margin-bottom:12px;">
                <div class="metric-title" data-i18n="dashboard.revenue"></div>
                <div class="metric-value" style="font-size:28px;">${window.ui.money(data.revenue)}</div>
            </div>
            <div class="card" style="display:flex;justify-content:space-between;align-items:center;">
                <div>
                    <div class="metric-title" data-i18n="dashboard.net_profit"></div>
                    <div class="metric-value ${data.net_profit < 0 ? 'text-danger' : ''}">${window.ui.money(data.net_profit)}</div>
                </div>
            </div>
            <div class="card" style="display:flex;justify-content:space-between;align-items:center;cursor:pointer;" id="cash-card">
                <div>
                    <div class="metric-title" data-i18n="dashboard.cash_balance"></div>
                    <div class="metric-value">${window.ui.money(data.cash)}</div>
                </div>
                <span class="text-muted font-bold" style="font-size:18px;">›</span>
            </div>

            <div class="metrics-grid">
                <div class="metric-card yellow">
                    <div class="metric-title" data-i18n="finance.expenses"></div>
                    <div class="metric-value" style="font-size:17px;">${window.ui.money(data.expenses_total)}</div>
                </div>
                <div class="metric-card purple">
                    <div class="metric-title" data-i18n="finance.gross_profit"></div>
                    <div class="metric-value" style="font-size:17px;">${window.ui.money(data.gross_profit)}</div>
                </div>
                <div class="metric-card blue">
                    <div class="metric-title" data-i18n="finance.client_debts"></div>
                    <div class="metric-value" style="font-size:17px;">${window.ui.money(data.client_debts)}</div>
                </div>
                <div class="metric-card green">
                    <div class="metric-title" data-i18n="finance.worker_debts"></div>
                    <div class="metric-value" style="font-size:17px;">${window.ui.money(data.worker_debts)}</div>
                </div>
            </div>

            ${data.stock.low_stock_materials > 0 ? `
                <a class="alert-box" href="#/warehouse" style="text-decoration:none;justify-content:space-between;">
                    <span>⚠️ <span data-i18n="warehouse.low_stock_warning"></span> (${data.stock.low_stock_materials})</span>
                    <span>›</span>
                </a>` : ''}

            ${data.top_products.length ? `
                <div class="section-title" data-i18n="finance.top_selling"></div>
                <div class="list-group">
                    ${data.top_products.map((p) => `
                        <div class="list-row" style="cursor:default;">
                            <span>${window.ui.escape(p.name)}</span>
                            <span class="font-bold">${window.ui.qty(p.total_quantity)}</span>
                        </div>`).join('')}
                </div>` : ''}

            ${data.most_active_worker ? `
                <div class="section-title" data-i18n="finance.most_active_worker"></div>
                <div class="card" style="display:flex;justify-content:space-between;">
                    <span>${window.ui.escape(data.most_active_worker.name || data.most_active_worker.username)}</span>
                    <span class="font-bold">${window.ui.qty(data.most_active_worker.total_quantity)}</span>
                </div>` : ''}
        `;

        container.querySelectorAll('[data-period]').forEach((btn) => {
            btn.addEventListener('click', () => {
                this.period = btn.dataset.period;
                this.renderOwner(container).then(() => window.i18n.applyTranslations());
            });
        });
        const cashCard = container.querySelector('#cash-card');
        if (cashCard) cashCard.addEventListener('click', () => window.router.navigate('/finance'));
    }

    async renderAdmin(container) {
        const data = await window.api.request('/reports/analytics/admin/');
        const user = window.currentUser;

        container.innerHTML = `
            <div style="margin-bottom:15px;">
                <h3 style="font-size:16px;margin-bottom:4px;">
                    <span data-i18n="dashboard.welcome"></span>, ${window.ui.escape(user.full_name || user.username)}!
                </h3>
                <span class="text-sm text-muted" data-i18n="dashboard.today_indicators"></span>
            </div>
            <div class="metrics-grid">
                <div class="metric-card green">
                    <div class="metric-title" data-i18n="dashboard.new_orders"></div>
                    <div class="metric-value">${data.orders_new}</div>
                </div>
                <div class="metric-card yellow">
                    <div class="metric-title" data-i18n="dashboard.in_progress"></div>
                    <div class="metric-value">${data.orders_in_progress}</div>
                </div>
                <div class="metric-card blue">
                    <div class="metric-title" data-i18n="statuses.ready"></div>
                    <div class="metric-value">${data.orders_ready}</div>
                </div>
                <div class="metric-card purple">
                    <div class="metric-title" data-i18n="dashboard.pending_confirmations"></div>
                    <div class="metric-value">${data.awaiting_confirmation}</div>
                </div>
            </div>

            ${data.orders_overdue > 0 ? `
                <a class="alert-box" href="#/orders" style="text-decoration:none;justify-content:space-between;">
                    <span>⏰ <span data-i18n="dashboard.deadline_passed"></span>: ${data.orders_overdue}</span><span>›</span>
                </a>` : ''}

            ${data.low_stock_materials.length ? `
                <a class="alert-box" href="#/warehouse" style="text-decoration:none;justify-content:space-between;">
                    <span>⚠️ <span data-i18n="warehouse.low_stock_warning"></span> (${data.low_stock_materials.length})</span>
                    <span>›</span>
                </a>` : ''}

            ${data.unpaid_clients.length ? `
                <div class="section-title" data-i18n="admin_analytics.unpaid_clients"></div>
                <div class="list-group">
                    ${data.unpaid_clients.map((c) => `
                        <div class="list-row" style="cursor:default;">
                            <span>${window.ui.escape(c.name)}</span>
                            <span class="badge badge-cancel" data-i18n="payment_statuses.unpaid"></span>
                        </div>`).join('')}
                </div>` : ''}

            ${data.worker_performance.length ? `
                <div class="section-title" data-i18n="admin_analytics.worker_performance"></div>
                <div class="list-group">
                    ${data.worker_performance.map((w) => `
                        <div class="list-row" style="cursor:default;">
                            <span>${window.ui.escape(w.worker_full_name || w.worker_username)}</span>
                            <span class="font-bold">${window.ui.qty(w.total_quantity)}</span>
                        </div>`).join('')}
                </div>` : ''}
        `;
    }

    async renderWorker(container) {
        const [tasksResp, earnings] = await Promise.all([
            window.api.request('/production/tasks/'),
            window.api.request('/production/works/my_earnings/'),
        ]);
        const tasks = tasksResp.results || tasksResp;
        const pending = tasks.filter((t) => t.status === 'pending');
        const active = tasks.filter((t) => ['accepted', 'in_progress'].includes(t.status));
        const user = window.currentUser;

        container.innerHTML = `
            <div style="margin-bottom:15px;">
                <h3 style="font-size:16px;margin-bottom:4px;">
                    <span data-i18n="dashboard.worker_greeting"></span> ${window.ui.escape(user.full_name || user.username)}!
                </h3>
                <span class="text-sm text-muted" data-i18n="nav.my_tasks"></span>
            </div>
            <div class="metrics-grid">
                <div class="metric-card yellow">
                    <div class="metric-title" data-i18n="production.pending_tasks"></div>
                    <div class="metric-value">${pending.length}</div>
                </div>
                <div class="metric-card blue">
                    <div class="metric-title" data-i18n="production.in_progress_tasks"></div>
                    <div class="metric-value">${active.length}</div>
                </div>
                <div class="metric-card green">
                    <div class="metric-title" data-i18n="worker_section.total_earned"></div>
                    <div class="metric-value" style="font-size:17px;">${window.ui.money(earnings.total_earned)}</div>
                </div>
                <div class="metric-card purple">
                    <div class="metric-title" data-i18n="worker_section.remaining"></div>
                    <div class="metric-value" style="font-size:17px;">${window.ui.money(earnings.remaining)}</div>
                </div>
            </div>

            ${pending.length ? `
                <div class="section-title" data-i18n="production.pending_tasks"></div>
                <div class="list-group">
                    ${pending.map((t) => `
                        <a class="list-row" href="#/production" style="text-decoration:none;color:inherit;">
                            <span>#${t.id} ${window.ui.escape(t.order_product || '')}</span>
                            ${window.ui.workBadge(t.status)}
                        </a>`).join('')}
                </div>` : `
                <div class="card list-state" data-i18n="production.no_pending_tasks"></div>`}

            <a class="btn btn-primary btn-block" href="#/production" style="margin-top:10px;" data-i18n="worker_section.add_work"></a>
        `;
    }
}

window.DashboardComponent = new DashboardComponent();
