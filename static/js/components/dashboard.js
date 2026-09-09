/**
 * Дашборд: у каждой роли своя главная.
 * Owner - финансовая аналитика, Admin - операционные показатели без денег,
 * Worker - задачи на сегодня и заработок.
 * SuperAdmin - Платформенный дашборд (компании, подписки, статистика).
 */
class DashboardComponent {
    async render(container) {
        document.getElementById('page-title').setAttribute('data-i18n', 'nav.dashboard');
        window.i18n.applyTranslations();

        const user = window.currentUser;
        if (user.is_superadmin) {
            await this.renderSuperAdmin(container);
        } else if (user.is_owner) await this.renderOwner(container);
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

    async renderSuperAdmin(container) {
        document.getElementById('page-title').setAttribute('data-i18n', 'superadmin.dashboard_title');
        window.i18n.applyTranslations();

        let stats = {};
        try {
            stats = await window.api.request('/companies/stats/');
        } catch (e) {
            console.error('Failed to load platform stats', e);
        }

        container.innerHTML = `
            <div class="page-hero">
                <div>
                    <div class="eyebrow" data-i18n="superadmin.welcome"></div>
                    <h2 data-i18n="superadmin.dashboard_title"></h2>
                </div>
            </div>

            <div class="stat-grid">
                ${window.ui.statCard({ icon: window.icon('building', 18), color: 'blue', titleKey: 'superadmin.stat_total', value: stats.total || 0 })}
                ${window.ui.statCard({ icon: window.icon('check-circle', 18), color: 'green', titleKey: 'superadmin.stat_active', value: stats.active || 0 })}
                ${window.ui.statCard({ icon: window.icon('star', 18), color: 'teal', titleKey: 'superadmin.stat_trial', value: stats.trial || 0 })}
                ${window.ui.statCard({ icon: window.icon('clock', 18), color: 'orange', titleKey: 'superadmin.stat_grace', value: stats.grace || 0 })}
                ${window.ui.statCard({ icon: window.icon('alert-triangle', 18), color: 'purple', titleKey: 'superadmin.stat_expiring', value: stats.expiring_soon || 0 })}
                ${window.ui.statCard({ icon: window.icon('pause-circle', 18), color: 'red', titleKey: 'superadmin.stat_expired', value: stats.expired || 0 })}
                ${window.ui.statCard({ icon: window.icon('lock', 18), color: 'gray', titleKey: 'superadmin.stat_frozen', value: stats.frozen || 0 })}
                ${window.ui.statCard({ icon: window.icon('x-circle', 18), color: 'dark', titleKey: 'superadmin.stat_cancelled', value: stats.cancelled || 0 })}
            </div>

            ${(stats.expiring_soon > 0 || stats.grace > 0 || stats.frozen > 0) ? `
            <div class="alert-box alert-box-warning" style="margin-bottom:16px;">
                <span>${window.icon('alert-triangle', 16)} <strong data-i18n="superadmin.attention_needed"></strong></span>
                <span class="badge badge-progress">${stats.expiring_soon || 0} ${window.ui.t('superadmin.expiring_soon')}</span>
                ${stats.grace > 0 ? `<span class="badge badge-progress" style="margin-left:4px;">${stats.grace} ${window.ui.t('superadmin.in_grace')}</span>` : ''}
                ${stats.frozen > 0 ? `<span class="badge badge-progress" style="margin-left:4px;">${stats.frozen} ${window.ui.t('superadmin.frozen')}</span>` : ''}
            </div>` : ''}

            <div class="card-grid">
                <div class="card card-minimal">
                    <div class="card-title" data-i18n="superadmin.recent_activity"></div>
                    ${window.ui.statCard({ icon: window.icon('plus-circle', 18), color: 'blue', titleKey: 'superadmin.stat_recent_subs', value: stats.recent_subscriptions || 0 })}
                    ${window.ui.statCard({ icon: window.icon('repeat', 18), color: 'green', titleKey: 'superadmin.stat_recent_renewals', value: stats.recent_renewals || 0 })}
                </div>
                <div class="card card-minimal">
                    <div class="card-title" data-i18n="superadmin.quick_actions"></div>
                    <div style="display:flex;flex-direction:column;gap:8px;">
                        <a class="btn btn-primary btn-block" href="#/companies" data-i18n="superadmin.manage_companies"></a>
                        <a class="btn btn-secondary btn-block" href="#/messages?tab=notifications" data-i18n="superadmin.view_notifications"></a>
                        <a class="btn btn-secondary btn-block" href="#/settings" data-i18n="settings.title"></a>
                    </div>
                </div>
            </div>
        `;
    }

    analyticsQuery() {
        return window.ui.reportPeriodQuery({
            period: this.period || 'month',
            dateFrom: this.dateFrom,
            dateTo: this.dateTo,
        });
    }

    async renderOwner(container) {
        const period = this.period || 'month';
        const built = this.analyticsQuery();
        let data = null;
        if (!(period === 'custom' && built.error)) {
            data = await window.api.request(`/reports/analytics/owner/?${built.query}`);
        }

        const rangeText = data
            ? window.ui.reportPeriodRangeText(data.date_from, data.date_to)
            : '';
        const empty = {
            revenue: 0,
            net_profit: 0,
            cash: 0,
            low_stock_count: 0,
            client_debts: 0,
            deltas: {},
            stock: { low_stock_materials: 0 },
            top_products: [],
            most_active_worker: null,
            expenses_by_category: {},
        };
        const view = data || empty;

        container.innerHTML = `
            <div class="page-hero">
                <div>
                    <div class="eyebrow" data-i18n="dashboard.welcome_owner"></div>
                    <h2 data-i18n="dashboard.owner_overview"></h2>
                </div>
                <div class="tabs" role="tablist" aria-label="Dashboard period">
                    ${['today', 'week', 'month', 'quarter', 'year', 'custom'].map((p) => `<button class="tab-btn ${p === period ? 'active' : ''}" data-period="${p}" data-i18n="periods.${p}"></button>`).join('')}
                </div>
            </div>
            ${window.ui.customPeriodPanelHtml(this.dateFrom, this.dateTo, period === 'custom')}

            <div class="stat-grid">
                ${window.ui.statCard({ icon: window.icon('trending-up', 18), color: 'green', titleKey: 'dashboard.revenue', value: window.ui.money(view.revenue), delta: view.deltas?.revenue })}
                ${window.ui.statCard({ icon: window.icon('check-circle', 18), color: 'purple', titleKey: 'dashboard.net_profit', value: window.ui.money(view.net_profit), delta: view.deltas?.net_profit, valueClass: view.net_profit < 0 ? 'text-danger' : '' })}
                ${window.ui.statCard({ icon: window.icon('wallet', 18), color: 'blue', titleKey: 'dashboard.cash_balance', value: window.ui.money(view.cash), id: 'cash-card' })}
                ${window.ui.statCard({ icon: window.icon('alert-triangle', 18), color: 'orange', titleKey: 'dashboard.low_stock_count', value: view.low_stock_count || 0 })}
                ${window.ui.statCard({ icon: window.icon('users', 18), color: 'red', titleKey: 'finance.client_debts', value: window.ui.money(view.client_debts), valueClass: view.client_debts > 0 ? 'text-danger' : '', id: 'client-debts-card' })}
            </div>

            ${view.stock.low_stock_materials > 0 ? `
                <a class="alert-box alert-box-warning" href="#/warehouse" style="text-decoration:none;justify-content:space-between;">
                    <span>${window.icon('alert-triangle', 16)} <span data-i18n="warehouse.low_stock_warning"></span> (${view.stock.low_stock_materials})</span>
                    <span>›</span>
                </a>` : ''}

            <div class="card-grid">
                <div class="card card-minimal">
                    <div class="card-title" data-i18n="finance.expenses"></div>
                    ${window.ui.donutChart(this.expenseSegments(view), { centerLabel: window.ui.t('finance.expenses') })}
                </div>
                <div class="card card-minimal">
                    <div class="card-title" data-i18n="finance.top_selling"></div>
                    ${view.top_products.length ? `
                        <div class="list-group list-group-compact">
                            ${view.top_products.slice(0, 3).map((p) => `
                                <div class="list-row" style="cursor:default;">
                                    <span>${window.ui.escape(p.name)}</span>
                                    <span class="font-bold">${window.ui.qty(p.total_quantity)}</span>
                                </div>`).join('')}
                        </div>` : `<div class="list-state list-state-empty" data-i18n="common.no_data"></div>`}
                    ${view.most_active_worker ? `
                        <div class="section-title" data-i18n="finance.most_active_worker"></div>
                        <div class="list-row" style="cursor:default; justify-content: space-between;">
                            <span>${window.ui.escape(view.most_active_worker.name || view.most_active_worker.username)}</span>
                            ${this.workerOutput(view.most_active_worker)}
                        </div>` : ''}
                </div>
            </div>
        `;

        const labelEl = container.querySelector('#period-range-label');
        if (labelEl && rangeText) {
            labelEl.textContent = `${window.ui.t('periods.selected_range')}: ${rangeText}`;
        }
        window.ui.bindReportPeriodControls(container, this, () => {
            this.renderOwner(container).then(() => window.i18n.applyTranslations());
        });
        const cashCard = container.querySelector('#cash-card');
        if (cashCard) cashCard.addEventListener('click', () => window.router.navigate('/finance'));
        const clientDebtsCard = container.querySelector('#client-debts-card');
        if (clientDebtsCard) clientDebtsCard.addEventListener('click', () => window.router.navigate('/clients'));

        // Лента операций кассы
        this.renderCashFeed(container);
        if (data) this.renderRevenueChart(container, data);
    }

    /** Лента операций кассы (для владельца) */
    async renderCashFeed(container) {
        try {
            const [expensesResp, paymentsResp, clientPaysResp] = await Promise.all([
                window.api.request('/finance/expenses/?page_size=5'),
                window.api.request('/finance/worker-payments/?page_size=5'),
                window.api.request('/clients/payments/?page_size=5').catch(() => ({ results: [] })),
            ]);
            const expenses = (expensesResp.results || expensesResp).slice(0, 5);
            const payments = (paymentsResp.results || paymentsResp).slice(0, 5);
            const incoming = (clientPaysResp.results || clientPaysResp).slice(0, 5);
            // Объединяем и сортируем по дате. Приходы клиентов — плюс, расходы
            // и выплаты работникам — минус (макет ленты кассы).
            const operations = []
                .concat(expenses.map(e => ({ type: 'expense', date: e.date, amount: -e.amount, desc: window.ui.t('expense_categories.' + e.category) })))
                .concat(payments.map(p => ({ type: 'payment', date: p.payment_date, amount: -p.amount, desc: window.ui.t('payment_types.' + p.payment_type) + ': ' + (p.worker_name || '') })))
                .concat(incoming.map(p => ({
                    type: 'in',
                    date: p.payment_date,
                    amount: Number(p.amount),
                    desc: window.ui.t('finance.client_payment') + ': ' + (p.client_name || ''),
                })))
                .sort((a, b) => new Date(b.date) - new Date(a.date))
                .slice(0, 7);
            if (!operations.length) return;
            const wrap = document.createElement('div');
            wrap.innerHTML = `
                <div class="section-title" style="display:flex;justify-content:space-between;align-items:center;">
                    <span data-i18n="dashboard.cash_operations"></span>
                    <a href="#/finance" class="text-sm" style="color:var(--primary);"><span data-i18n="common.view_all"></span> ›</a>
                </div>
                <div class="list-group list-group-compact">
                    ${operations.map(op => `
                        <div class="list-row" style="cursor:default;">
                            <div style="min-width:0;">
                                <div style="font-weight:600;font-size:14px;">${window.ui.escape(op.desc)}</div>
                                <div class="text-sm text-muted">${window.ui.date(op.date)}</div>
                            </div>
                            <span class="font-bold ${Number(op.amount) >= 0 ? 'text-success' : ''}"
                                  style="${Number(op.amount) >= 0 ? '' : 'color:var(--danger-color);'}">${Number(op.amount) > 0 ? '+' : ''}${window.ui.money(op.amount)}</span>
                        </div>
                    `).join('')}
                </div>
            `;
            container.appendChild(wrap);
            window.i18n.applyTranslations();
        } catch (e) {
            // Лента некритична
        }
    }

    /** Выработка работника: с единицей измерения, а при разных единицах — разбивкой (складывать нельзя). */
    workerOutput(worker) {
        const totals = worker.unit_totals || [];
        if (!totals.length) return `<span class="font-bold">${window.ui.qty(0)}</span>`;
        if (totals.length === 1) {
            return `<span class="font-bold">${window.ui.qty(totals[0].total_quantity)} ${window.ui.escape(window.ui.t('units.' + totals[0].unit))}</span>`;
        }
        return `<span class="font-bold">${totals.map((t) =>
            `${window.ui.qty(t.total_quantity)} ${window.ui.escape(window.ui.t('units.' + t.unit))}`
        ).join('<br>')}</span>`;
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
            <div class="card" style="padding:18px;">
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
                        borderColor: '#0071e3',
                        backgroundColor: 'rgba(0, 113, 227, 0.08)',
                        borderWidth: 2.5,
                        fill: true,
                        tension: 0.3,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        pointBackgroundColor: '#0071e3',
                    }, {
                        label: window.ui.t('finance.net_profit'),
                        data: chartData.net_profits,
                        borderColor: '#34c759',
                        backgroundColor: 'rgba(52, 199, 89, 0.06)',
                        borderWidth: 2,
                        fill: true,
                        tension: 0.3,
                        pointRadius: 3,
                        pointHoverRadius: 5,
                        pointBackgroundColor: '#34c759',
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
        // Квартальный операционный отчёт по ТЗ есть и у администратора —
        // без единой денежной цифры (сервер отдаёт вариант kind=operational).
        const [data, quarter, conversations] = await Promise.all([
            window.api.request('/reports/analytics/admin/'),
            window.api.request('/reports/analytics/quarterly/').catch(() => null),
            // Непрочитанные от работников — из уже существующего списка
            // бесед (kind + other_user.role + unread_count), без нового API.
            window.api.request('/messaging/conversations/?page_size=100').catch(() => null),
        ]);
        const convRows = (conversations && conversations.results) || conversations || [];
        const workerUnread = (Array.isArray(convRows) ? convRows : []).reduce((sum, conv) => {
            const other = conv.other_user || {};
            if (conv.kind === 'direct' && other.role === 'worker') {
                return sum + (conv.unread_count || 0);
            }
            return sum;
        }, 0);
        const user = window.currentUser;

        container.innerHTML = `
            <div class="page-hero">
                <div>
                    <div class="eyebrow" data-i18n="dashboard.welcome"></div>
                    <h2>${window.ui.escape(user.full_name || user.username)}</h2>
                </div>
                <a class="btn btn-primary btn-sm" href="#/orders" data-i18n="dashboard.open_orders"></a>
            </div>

            <div class="stat-grid">
                ${window.ui.statCard({ icon: window.icon('inbox', 18), color: 'green', titleKey: 'dashboard.new_orders', value: data.orders_new, href: '#/orders' })}
                ${window.ui.statCard({ icon: window.icon('clock', 18), color: 'orange', titleKey: 'dashboard.in_progress', value: data.orders_in_progress, href: '#/orders' })}
                ${window.ui.statCard({ icon: window.icon('check-circle', 18), color: 'blue', titleKey: 'statuses.ready', value: data.orders_ready, href: '#/orders' })}
                ${window.ui.statCard({ icon: window.icon('alert-triangle', 18), color: 'red', titleKey: 'dashboard.overdue_orders', value: data.orders_overdue, href: '#/orders' })}
                ${window.ui.statCard({ icon: window.icon('layers', 18), color: 'purple', titleKey: 'dashboard.pending_confirmations', value: data.awaiting_confirmation || 0, href: '#/production' })}
                ${window.ui.statCard({ icon: window.icon('check-circle', 18), color: 'teal', titleKey: 'dashboard.submitted_today', value: data.submitted_today || 0, href: '#/production' })}
                ${window.ui.statCard({ icon: window.icon('message', 18), color: 'blue', titleKey: 'dashboard.worker_unread', value: workerUnread, href: '#/messages' })}
            </div>

            ${data.low_stock_materials.length ? `
                <a class="alert-box" href="#/warehouse" style="text-decoration:none;justify-content:space-between;">
                    <span>${window.icon('alert-triangle', 16)} <span data-i18n="warehouse.low_stock_warning"></span> (${data.low_stock_materials.length})</span>
                    <span>›</span>
                </a>` : ''}

            ${data.unpaid_clients.length ? `
                <div class="section-title" data-i18n="admin_analytics.unpaid_clients"></div>
                <div class="list-group list-group-compact">
                    ${data.unpaid_clients.slice(0, 3).map((c) => `
                        <a class="list-row" href="#/orders?client=${c.id}&payment_status=unpaid" style="text-decoration:none;color:inherit;">
                            <span>${window.ui.escape(c.name)}</span>
                            <span class="badge badge-cancel" data-i18n="payment_statuses.unpaid"></span>
                        </a>`).join('')}
                </div>` : ''}

            ${quarter ? `
                <div class="section-title">
                    <span data-i18n="admin_analytics.quarterly"></span>
                    · ${window.ui.t('finance.quarter_label', { quarter: quarter.quarter, year: quarter.year })}
                </div>
                <div class="list-group list-group-compact">
                    <div class="list-row"><span data-i18n="admin_analytics.orders_total"></span><span>${quarter.orders_total}</span></div>
                    <div class="list-row"><span data-i18n="admin_analytics.orders_delivered"></span><span>${quarter.orders_delivered}</span></div>
                    <div class="list-row"><span data-i18n="admin_analytics.produced"></span><span>${window.ui.qty(quarter.produced_quantity)}</span></div>
                    <div class="list-row"><span data-i18n="admin_analytics.defects"></span><span>${window.ui.qty(quarter.defect_quantity)}</span></div>
                </div>` : ''}
        `;
        const confirmCard = container.querySelector('#awaiting-confirm-card');
        if (confirmCard) {
            confirmCard.style.cursor = 'pointer';
            confirmCard.addEventListener('click', () => window.router.navigate('/production'));
        }
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
            <div class="page-hero">
                <div>
                    <div class="eyebrow" data-i18n="dashboard.worker_overview"></div>
                    <h2>${window.ui.escape(user.full_name || user.username)}</h2>
                </div>
                <a class="btn btn-primary btn-sm" href="#/production" data-i18n="production.open_tasks"></a>
            </div>

            <div class="stat-grid">
                ${window.ui.statCard({ icon: window.icon('inbox', 18), color: 'orange', titleKey: 'production.pending_tasks', value: pending.length })}
                ${window.ui.statCard({ icon: window.icon('layers', 18), color: 'blue', titleKey: 'production.in_progress_tasks', value: active.length })}
                ${window.ui.statCard({ icon: window.icon('coins', 18), color: 'green', titleKey: 'worker_section.total_earned', value: window.ui.money(earnings.total_earned) })}
                ${window.ui.statCard({ icon: window.icon('banknote', 18), color: 'purple', titleKey: 'worker_section.remaining', value: window.ui.money(earnings.remaining) })}
            </div>

            ${pending.length ? `
                <div class="section-title" data-i18n="production.pending_tasks"></div>
                <div class="list-group list-group-compact">
                    ${pending.slice(0, 4).map((t) => `
                        <a class="list-row" href="#/production" style="text-decoration:none;color:inherit;">
                            <span>#${t.id} ${window.ui.escape(t.order_product || '')}</span>
                            ${window.ui.workBadge(t.status)}
                        </a>`).join('')}
                </div>` : `
                <div class="card list-state" data-i18n="production.no_pending_tasks"></div>`}
        `;
    }
}

window.DashboardComponent = new DashboardComponent();
