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
        else if (user.is_admin || user.is_manager) await this.renderAdmin(container);
        else await this.renderWorker(container);
        window.i18n.applyTranslations();
    }

    /** Преобразует expenses_by_category в сегменты для пончика (с переводом категорий). */
    expenseSegments(data) {
        const byCat = data.expenses_by_category || {};
        return Object.keys(byCat)
            .map((cat) => ({ label: window.ui.t('expense_categories.' + cat), value: Number(byCat[cat]) }))
            .filter((s) => s.value > 0)
            .sort((a, b) => b.value - a.value);
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

            <div class="stat-grid">
                ${window.ui.statCard({ icon: window.icon('trending-up', 18), color: 'green', titleKey: 'dashboard.revenue', value: window.ui.money(data.revenue), delta: data.deltas?.revenue })}
                ${window.ui.statCard({ icon: window.icon('check-circle', 18), color: 'green', titleKey: 'dashboard.net_profit', value: window.ui.money(data.net_profit), delta: data.deltas?.net_profit, valueClass: data.net_profit < 0 ? 'text-danger' : '' })}
                ${window.ui.statCard({ icon: window.icon('wallet', 18), color: 'blue', titleKey: 'dashboard.cash_balance', value: window.ui.money(data.cash), id: 'cash-card' })}
                ${window.ui.statCard({ icon: window.icon('pie-chart', 18), color: 'purple', titleKey: 'finance.gross_profit', value: window.ui.money(data.gross_profit) })}
                ${window.ui.statCard({ icon: window.icon('receipt', 18), color: 'orange', titleKey: 'finance.expenses', value: window.ui.money(data.expenses_total), delta: data.deltas?.expenses_total })}
                ${window.ui.statCard({ icon: window.icon('users', 18), color: 'red', titleKey: 'finance.client_debts', value: window.ui.money(data.client_debts), valueClass: data.client_debts > 0 ? 'text-danger' : '' })}
                ${window.ui.statCard({ icon: window.icon('wrench', 18), color: 'blue', titleKey: 'finance.worker_debts', value: window.ui.money(data.worker_debts) })}

                ${window.ui.statCard({ icon: window.icon('users', 18), color: 'blue', titleKey: 'dashboard.active_employees', value: data.active_employees_count || 0 })}
                ${window.ui.statCard({ icon: window.icon('clock', 18), color: 'red', titleKey: 'dashboard.overdue_percentage', value: (data.overdue_percentage || 0) + '%' })}
                ${window.ui.statCard({ icon: window.icon('alert-triangle', 18), color: 'orange', titleKey: 'dashboard.low_stock_count', value: data.low_stock_count || 0 })}
            </div>

            ${data.stock.low_stock_materials > 0 ? `
                <a class="alert-box" href="#/warehouse" style="text-decoration:none;justify-content:space-between;">
                    <span>${window.icon('alert-triangle', 16)} <span data-i18n="warehouse.low_stock_warning"></span> (${data.stock.low_stock_materials})</span>
                    <span>›</span>
                </a>` : ''}

            <div class="dash-2col">
                <div>
                    <div class="section-title" data-i18n="finance.expenses"></div>
                    <div class="card">
                        ${window.ui.donutChart(this.expenseSegments(data), { centerLabel: window.ui.t('finance.expenses') })}
                    </div>
                </div>
                <div>
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
                        <div class="list-group">
                            <div class="list-row" style="cursor:default;">
                                <span>${window.ui.escape(data.most_active_worker.name || data.most_active_worker.username)}</span>
                                <span class="font-bold">${window.ui.qty(data.most_active_worker.total_quantity)}</span>
                            </div>
                        </div>` : ''}
                </div>
            </div>
        `;

        container.querySelectorAll('[data-period]').forEach((btn) => {
            btn.addEventListener('click', () => {
                this.period = btn.dataset.period;
                this.renderOwner(container).then(() => window.i18n.applyTranslations());
            });
        });
        const cashCard = container.querySelector('#cash-card');
        if (cashCard) cashCard.addEventListener('click', () => window.router.navigate('/finance'));

        // График выручки
        this.renderRevenueChart(container, data);
    }

    async renderRevenueChart(container, data) {
        // Пробуем получить данные за 6 месяцев
        let chartData;
        try {
            chartData = await window.api.request('/reports/analytics/revenue-timeline/');
        } catch (e) {
            return; // не критично
        }
        if (!chartData || !chartData.labels || !chartData.labels.length) return;

        // Удаляем старый canvas если был
        const oldWrap = container.querySelector('.revenue-chart-wrap');
        if (oldWrap) oldWrap.remove();

        const wrap = document.createElement('div');
        wrap.className = 'revenue-chart-wrap';
        wrap.innerHTML = `
            <div class="section-title" data-i18n="dashboard.revenue_by_period"></div>
            <div class="card" style="padding:12px;">
                <canvas id="revenue-chart-canvas" height="200"></canvas>
            </div>
        `;
        container.appendChild(wrap);
        window.i18n.applyTranslations();

        const canvas = wrap.querySelector('#revenue-chart-canvas');
        if (!canvas) return;

        try {
            const ctx = canvas.getContext('2d');
            if (window._revenueChart) {
                window._revenueChart.destroy();
            }
            window._revenueChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: chartData.labels,
                    datasets: [{
                        label: window.ui.t('dashboard.revenue'),
                        data: chartData.revenues,
                        borderColor: '#197387',
                        backgroundColor: 'rgba(25, 115, 135, 0.08)',
                        borderWidth: 2.5,
                        fill: true,
                        tension: 0.3,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        pointBackgroundColor: '#197387',
                    }, {
                        label: window.ui.t('finance.net_profit'),
                        data: chartData.net_profits,
                        borderColor: '#3d8662',
                        backgroundColor: 'rgba(61, 134, 98, 0.06)',
                        borderWidth: 2,
                        fill: true,
                        tension: 0.3,
                        pointRadius: 3,
                        pointHoverRadius: 5,
                        pointBackgroundColor: '#3d8662',
                        borderDash: [5, 3],
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: true,
                            position: 'bottom',
                            labels: { boxWidth: 12, padding: 12, font: { size: 11 } }
                        },
                        tooltip: {
                            callbacks: {
                                label: (ctx) => {
                                    const val = Number(ctx.raw || 0).toLocaleString('ru-RU');
                                    return ` ${ctx.dataset.label}: ${val} ${window.ui.t('common.currency')}`;
                                }
                            }
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: {
                                callback: (v) => Number(v).toLocaleString('ru-RU'),
                                font: { size: 10 }
                            },
                            grid: { color: 'rgba(0,0,0,0.04)' }
                        },
                        x: {
                            ticks: { font: { size: 10 } },
                            grid: { display: false }
                        }
                    }
                }
            });
        } catch (e) {
            // Chart.js not loaded
        }
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
            <div class="stat-grid">
                ${window.ui.statCard({ icon: window.icon('inbox', 18), color: 'green', titleKey: 'dashboard.new_orders', value: data.orders_new })}
                ${window.ui.statCard({ icon: window.icon('clock', 18), color: 'orange', titleKey: 'dashboard.in_progress', value: data.orders_in_progress })}
                ${window.ui.statCard({ icon: window.icon('check-circle', 18), color: 'blue', titleKey: 'statuses.ready', value: data.orders_ready })}
                ${window.ui.statCard({ icon: window.icon('clipboard-list', 18), color: 'purple', titleKey: 'dashboard.pending_confirmations', value: data.awaiting_confirmation })}
            </div>

            ${data.orders_overdue > 0 ? `
                <a class="alert-box" href="#/orders" style="text-decoration:none;justify-content:space-between;">
                    <span>${window.icon('clock', 16)} <span data-i18n="dashboard.deadline_passed"></span>: ${data.orders_overdue}</span><span>›</span>
                </a>` : ''}

            ${data.low_stock_materials.length ? `
                <a class="alert-box" href="#/warehouse" style="text-decoration:none;justify-content:space-between;">
                    <span>${window.icon('alert-triangle', 16)} <span data-i18n="warehouse.low_stock_warning"></span> (${data.low_stock_materials.length})</span>
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
            <div class="stat-grid">
                ${window.ui.statCard({ icon: window.icon('inbox', 18), color: 'orange', titleKey: 'production.pending_tasks', value: pending.length })}
                ${window.ui.statCard({ icon: window.icon('layers', 18), color: 'blue', titleKey: 'production.in_progress_tasks', value: active.length })}
                ${window.ui.statCard({ icon: window.icon('coins', 18), color: 'green', titleKey: 'worker_section.total_earned', value: window.ui.money(earnings.total_earned) })}
                ${window.ui.statCard({ icon: window.icon('banknote', 18), color: 'purple', titleKey: 'worker_section.remaining', value: window.ui.money(earnings.remaining) })}
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
