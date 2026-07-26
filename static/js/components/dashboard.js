/**
 * DashboardComponent - главная страница с финансовой аналитикой.
 *
 * Показывает ключевые метрики бизнеса для владельца:
 * - Выручка, валовая/чистая прибыль, расходы, касса
 * - Операционные метрики для администратора
 * - Свои задачи для работника
 */
class DashboardComponent {
    async render(container) {
        container.innerHTML = `
            <header style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                <h1 data-i18n="dashboard.welcome">Хуш келибсиз</h1>
                <div style="display: flex; gap: 10px; align-items: center;">
                    <select id="period-select" class="form-control" style="width: auto;">
                        <option value="today" data-i18n="periods.today">Бугун</option>
                        <option value="yesterday" data-i18n="periods.yesterday">Кеча</option>
                        <option value="week" data-i18n="periods.week">Ҳафта</option>
                        <option value="month" selected data-i18n="periods.month">Ой</option>
                        <option value="quarter" data-i18n="periods.quarter">Чорак</option>
                        <option value="year" data-i18n="periods.year">Йил</option>
                    </select>
                    <select id="lang-select-dash" class="form-control" style="width: auto;">
                        <option value="uz_cyrl">Ўзбекча</option>
                        <option value="ru">Русский</option>
                    </select>
                </div>
            </header>

            <div id="dashboard-stats">
                <div style="text-align: center; padding: 40px;" data-i18n="common.loading">Юкланмоқда...</div>
            </div>
        `;

        window.i18n.applyTranslations();

        const langSelect = container.querySelector('#lang-select-dash');
        langSelect.value = window.i18n.currentLang;
        langSelect.addEventListener('change', (e) => {
            window.i18n.setLanguage(e.target.value);
        });

        const periodSelect = container.querySelector('#period-select');
        periodSelect.addEventListener('change', () => this.loadStats(container));

        await this.loadStats(container);
    }

    async loadStats(container) {
        const statsEl = container.querySelector('#dashboard-stats');
        try {
            const user = await window.api.getMe();
            const isOwner = user.is_owner;

            // Загружаем базовую статистику дашборда
            const dashboardData = await window.api.request('/core/dashboard/');

            // Если владелец - загружаем финансовую аналитику
            let financeData = null;
            if (isOwner) {
                const period = container.querySelector('#period-select').value;
                try {
                    financeData = await window.api.request(`/finance/analytics/?period=${period}`);
                } catch (e) {
                    console.warn('Finance analytics not available', e);
                }
            }

            // Рендерим карточки
            statsEl.innerHTML = this.renderStats(dashboardData, financeData, isOwner, user);
            window.i18n.applyTranslations();

        } catch (e) {
            console.error('Failed to load dashboard stats', e);
            statsEl.innerHTML = `<div class="card" style="padding: 20px; text-align: center; color: red;" data-i18n="common.error">Хатолик</div>`;
            window.i18n.applyTranslations();
        }
    }

    renderStats(dashboard, finance, isOwner, user) {
        let html = '';
        const gridStyle = 'style="display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 16px; margin-bottom: 24px;"';
        const showOwner = isOwner && finance;
        const showOp = !isOwner || !finance;

        // Открываем stats-grid ТОЛЬКО для operational метрик (не owner)
        if (showOp) {
            html += `<div class="stats-grid" ${gridStyle}>`;
        }

        // Финансовые карточки (только для owner, в своём grid)
        if (showOwner) {
            html += `<div class="stats-grid" ${gridStyle}>`;
            const metrics = [
                { key: 'finance.revenue', value: finance.revenue, icon: '💰', color: '#2e7d32' },
                { key: 'finance.gross_profit', value: finance.gross_profit, icon: '📈', color: '#1565c0' },
                { key: 'finance.net_profit', value: finance.net_profit, icon: '🏆', color: finance.net_profit >= 0 ? '#2e7d32' : '#c62828' },
                { key: 'finance.cash_in_register', value: finance.cash_in_register, icon: '💵', color: '#6a1b9a' },
                { key: 'finance.expenses', value: finance.expenses_total, icon: '📤', color: '#e65100' },
                { key: 'finance.salaries', value: finance.salaries_total, icon: '👷', color: '#4e342e' },
                { key: 'finance.client_debts', value: finance.client_debts_total, icon: '📋', color: '#b71c1c' },
            ];

            metrics.forEach(m => {
                const numValue = parseFloat(m.value) || 0;
                const formatted = numValue.toLocaleString('uz-UZ', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
                html += `
                    <div class="card" style="border-left: 4px solid ${m.color}; padding: 16px;">
                        <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                            <div>
                                <div style="font-size: 12px; color: #666; margin-bottom: 4px;" data-i18n="${m.key}">${m.key}</div>
                                <div style="font-size: 24px; font-weight: bold; color: ${m.color};">${formatted}</div>
                            </div>
                            <div style="font-size: 28px;">${m.icon}</div>
                        </div>
                    </div>
                `;
            });

            // Топ продаваемые товары (за период)
            if (finance.top_products && finance.top_products.length > 0) {
                html += `
                    </div>
                    <div class="card" style="padding: 16px; margin-bottom: 16px;">
                        <h3 style="margin-bottom: 12px;" data-i18n="dashboard.top_products">Энг кўп сотилган</h3>
                        <table style="width: 100%; border-collapse: collapse;">
                            <thead>
                                <tr style="border-bottom: 2px solid #eee;">
                                    <th style="padding: 8px; text-align: left;">#</th>
                                    <th style="padding: 8px; text-align: left;" data-i18n="common.name">Номи</th>
                                    <th style="padding: 8px; text-align: right;" data-i18n="common.quantity">Миқдор</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${finance.top_products.map((p, i) => `
                                    <tr style="border-bottom: 1px solid #f0f0f0;">
                                        <td style="padding: 8px;">${i + 1}</td>
                                        <td style="padding: 8px;">${p.name}</td>
                                        <td style="padding: 8px; text-align: right; font-weight: bold;">${p.quantity}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                `;
            }

            // Активность работников за период
            if (finance.worker_stats && finance.worker_stats.length > 0) {
                html += `
                    <div class="card" style="padding: 16px; margin-bottom: 16px;">
                        <h3 style="margin-bottom: 12px;" data-i18n="dashboard.most_active_worker">Энг фаол ишчи</h3>
                        <table style="width: 100%; border-collapse: collapse;">
                            <thead>
                                <tr style="border-bottom: 2px solid #eee;">
                                    <th style="padding: 8px; text-align: left;">#</th>
                                    <th style="padding: 8px; text-align: left;" data-i18n="finance.worker">Ишчи</th>
                                    <th style="padding: 8px; text-align: right;" data-i18n="common.count">Сони</th>
                                    <th style="padding: 8px; text-align: right;" data-i18n="finance.total_earned">Топган</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${finance.worker_stats.map((w, i) => `
                                    <tr style="border-bottom: 1px solid #f0f0f0;">
                                        <td style="padding: 8px;">${i + 1}</td>
                                        <td style="padding: 8px;">${w.username}</td>
                                        <td style="padding: 8px; text-align: right;">${w.works_count}</td>
                                        <td style="padding: 8px; text-align: right; font-weight: bold;">${parseFloat(w.total_earned || 0).toLocaleString('uz-UZ', { minimumFractionDigits: 2 })}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                `;
            }
        }

        // Операционные метрики (видят все)
        const opMetrics = [
            { key: 'dashboard.new_orders', value: dashboard.new_orders_count || 0, icon: '📦', color: '#1565c0' },
            { key: 'dashboard.in_progress', value: dashboard.in_progress_orders_count || 0, icon: '⚙️', color: '#e65100' },
            { key: 'dashboard.tasks_today', value: dashboard.today_tasks || 0, icon: '✅', color: '#2e7d32' },
            { key: 'dashboard.pending_confirmations', value: dashboard.pending_tasks || 0, icon: '⏳', color: '#f9a825' },
        ];

        if (showOp) {
            opMetrics.forEach(m => {
                html += `
                    <div class="card" style="border-left: 4px solid ${m.color}; padding: 16px;">
                        <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                            <div>
                                <div style="font-size: 12px; color: #666; margin-bottom: 4px;" data-i18n="${m.key}">${m.key}</div>
                                <div style="font-size: 24px; font-weight: bold; color: ${m.color};">${m.value}</div>
                            </div>
                            <div style="font-size: 28px;">${m.icon}</div>
                        </div>
                    </div>
                `;
            });
            html += '</div>';  // закрываем op stats-grid
        }

        // Дополнительные метрики в виде таблицы под карточками
        html += `
            <div class="card" style="padding: 16px;">
                <h3 style="margin-bottom: 12px;" data-i18n="dashboard.business_overview">Бизнесингизни тўлиқ кўринг</h3>
                <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px;">
                    <div style="padding: 12px; background: #f5f5f5; border-radius: 8px;">
                        <div style="font-size: 11px; color: #888;" data-i18n="dashboard.overdue_orders">Муддати ўтган</div>
                        <div style="font-size: 20px; font-weight: bold; color: ${(dashboard.overdue_orders_count || 0) > 0 ? '#c62828' : '#2e7d32'}">${dashboard.overdue_orders_count || 0}</div>
                    </div>
                    <div style="padding: 12px; background: #f5f5f5; border-radius: 8px;">
                        <div style="font-size: 11px; color: #888;" data-i18n="dashboard.low_stock">Кам қолдиқ</div>
                        <div style="font-size: 20px; font-weight: bold; color: ${(dashboard.low_stock_materials || 0) > 0 ? '#e65100' : '#2e7d32'}">${dashboard.low_stock_materials || 0}</div>
                    </div>
                    <div style="padding: 12px; background: #f5f5f5; border-radius: 8px;">
                        <div style="font-size: 11px; color: #888;" data-i18n="dashboard.total_materials">Материаллар</div>
                        <div style="font-size: 20px; font-weight: bold;">${dashboard.total_materials || 0}</div>
                    </div>
                    <div style="padding: 12px; background: #f5f5f5; border-radius: 8px;">
                        <div style="font-size: 11px; color: #888;" data-i18n="dashboard.total_clients">Мижозлар</div>
                        <div style="font-size: 20px; font-weight: bold;">${dashboard.total_clients || 0}</div>
                    </div>
                    <div style="padding: 12px; background: #f5f5f5; border-radius: 8px;">
                        <div style="font-size: 11px; color: #888;" data-i18n="dashboard.clients_with_debt">Қарздорлар</div>
                        <div style="font-size: 20px; font-weight: bold; color: ${(dashboard.clients_with_debt || 0) > 0 ? '#c62828' : '#2e7d32'}">${dashboard.clients_with_debt || 0}</div>
                    </div>
                    <div style="padding: 12px; background: #f5f5f5; border-radius: 8px;">
                        <div style="font-size: 11px; color: #888;" data-i18n="dashboard.unread_notifications">Хабарлар</div>
                        <div style="font-size: 20px; font-weight: bold;">${dashboard.unread_notifications || 0}</div>
                    </div>
                </div>
            </div>
        `;

        return html;
    }
}

window.DashboardComponent = new DashboardComponent();
