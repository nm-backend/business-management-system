/**
 * Продажи (Сотувлар) — экран хозяина из ТЗ (список главных экранов):
 * выданные клиенту заказы за период с деньгами и итогами.
 *
 * Данные: GET /reports/analytics/sales/ (IsOwner — деньги не уходят другим
 * ролям и на этом экране: маршрут #/sales зарегистрирован только владельцу).
 * Периоды — тот же серверный механизм, что у дашборда и аналитики
 * (_parse_period: today/yesterday/week/month/quarter/year + custom).
 */
class SalesComponent {
    constructor() {
        this.period = 'month';
        this.dateFrom = '';
        this.dateTo = '';
    }

    async render(container) {
        document.getElementById('page-title').setAttribute('data-i18n', 'sales.title');
        this.container = container;

        if (!window.currentUser.is_owner) {
            container.innerHTML = `
                <div class="card route-error">
                    <h1>403</h1>
                    <p data-i18n="common.no_access_hint"></p>
                </div>`;
            window.i18n.applyTranslations();
            return;
        }

        container.innerHTML = `
            <div class="page-hero">
                <div>
                    <div class="eyebrow" data-i18n="sales.title"></div>
                    <h2 data-i18n="sales.subtitle"></h2>
                </div>
                <div class="tabs" role="tablist" aria-label="Sales period">
                    ${['today', 'yesterday', 'week', 'month', 'quarter', 'year', 'custom'].map((p) =>
                        `<button class="tab-btn ${p === this.period ? 'active' : ''}" data-period="${p}" data-i18n="periods.${p}"></button>`).join('')}
                </div>
            </div>
            ${window.ui.customPeriodPanelHtml(this.dateFrom, this.dateTo, this.period === 'custom')}
            <div id="sales-content"></div>
        `;

        window.ui.bindReportPeriodControls(container, this, () => {
            this.render(container).then(() => window.i18n.applyTranslations());
        });
        window.i18n.applyTranslations();
        await this.load();
    }

    analyticsQuery() {
        return window.ui.reportPeriodQuery({
            period: this.period || 'month',
            dateFrom: this.dateFrom,
            dateTo: this.dateTo,
        });
    }

    async load() {
        const contentEl = this.container.querySelector('#sales-content');
        if (window.listStates.gone(contentEl)) return;
        const built = this.analyticsQuery();
        if (this.period === 'custom' && built.error) {
            contentEl.innerHTML = `<div class="card list-state" data-i18n="${built.error}"></div>`;
            window.i18n.applyTranslations();
            return;
        }
        window.listStates.loading(contentEl, window.ui.t('common.loading'));
        try {
            const data = await window.api.request(`/reports/analytics/sales/?${built.query}`);
            if (window.listStates.gone(contentEl)) return;
            const orders = data.orders || [];
            const rangeText = window.ui.reportPeriodRangeText(data.date_from, data.date_to);

            contentEl.innerHTML = `
                <div class="stat-grid">
                    ${window.ui.statCard({ icon: window.icon('trending-up', 18), color: 'green', titleKey: 'sales.total_amount', value: window.ui.money(data.total_amount) })}
                    ${window.ui.statCard({ icon: window.icon('check-circle', 18), color: 'blue', titleKey: 'clients.paid', value: window.ui.money(data.paid) })}
                    ${window.ui.statCard({ icon: window.icon('alert-triangle', 18), color: 'red', titleKey: 'clients.debt', value: window.ui.money(data.debt), valueClass: data.debt > 0 ? 'text-danger' : '' })}
                    ${window.ui.statCard({ icon: window.icon('package', 18), color: 'purple', titleKey: 'sales.count', value: data.count || 0 })}
                </div>
                ${!orders.length
                    ? `<div class="card list-state" data-i18n="sales.empty"></div>`
                    : `<div class="card">
                        <div class="card-title"><span data-i18n="sales.title"></span> ${rangeText ? `<span class="text-sm text-muted">· ${rangeText}</span>` : ''}</div>
                        <div class="list-group">
                            ${orders.map((o) => `
                                <div class="list-row" role="button" tabindex="0" data-order="${o.id}" data-client="${o.client || ''}" style="cursor:pointer;">
                                    <span style="min-width:0;">
                                        <span class="font-bold">#${o.id} ${window.ui.escape(o.client_name || '')}</span>
                                        <span class="text-sm text-muted" style="display:block;">
                                            ${window.ui.escape(o.product_name || '-')} × ${window.ui.qty(o.quantity)} <span data-i18n="units.${o.unit}"></span>
                                            · ${window.ui.datetime(o.delivered_at)}
                                        </span>
                                    </span>
                                    <span class="u-text-right" style="flex-shrink:0;">
                                        <span class="font-bold">${window.ui.money(o.total_amount)}</span>
                                        ${Number(o.debt || 0) > 0
                                            ? `<span class="text-sm text-danger" style="display:block;">${window.ui.t('clients.debt')}: ${window.ui.money(o.debt)}</span>`
                                            : `<span class="text-sm" style="display:block;color:var(--success-color);" data-i18n="payment_statuses.paid"></span>`}
                                    </span>
                                </div>`).join('')}
                        </div>
                    </div>`}
            `;

            contentEl.querySelectorAll('[data-order]').forEach((row) => {
                row.addEventListener('click', () => {
                    // Заказы именно этого клиента (глубокая ссылка поддержана в orders.js).
                    const clientId = row.dataset.client;
                    window.location.hash = clientId ? `#/orders?client=${clientId}` : '#/orders';
                });
            });
            window.i18n.applyTranslations();
        } catch (error) {
            window.listStates.error(contentEl, window.ui.errorText(error), () => this.load());
        }
    }
}

window.SalesComponent = new SalesComponent();
