/**
 * «Подписка» — собственная подписка компании для владельца и администратора.
 *
 * Показывает состояние подписки (статус, начало/окончание, остаток дней),
 * историю изменений и кнопку «Запросить продление»: запрос уходит суперадмину
 * в колокольчик (уведомление + push), менять подписку сам владелец не может.
 *
 * Компания берётся из /companies/my-subscription/ (сервер сам подставляет
 * компанию текущего пользователя — чужую указать невозможно).
 */
class SubscriptionComponent {
    async render(container) {
        const user = window.currentUser;
        if (!user || user.is_superadmin || !user.company_name) {
            window.location.hash = '#/';
            return;
        }
        document.getElementById('page-title').setAttribute('data-i18n', 'subscription.page_title');
        this.container = container;
        container.innerHTML = `<div class="list-state list-state-loading"><span class="spinner"></span></div>`;
        try {
            const data = await window.api.request('/companies/my-subscription/');
            this.renderData(container, data);
        } catch (e) {
            window.listStates.error(
                container,
                window.ui.errorText ? window.ui.errorText(e) : window.ui.t('common.error'),
                () => this.render(container),
            );
        }
    }

    renderData(container, data) {
        const status = data.subscription_status || 'active';
        const badgeClass = status === 'active' ? 'badge-ready'
            : (status === 'frozen' || status === 'grace') ? 'badge-progress'
            : 'badge-cancel';
        const isGrace = status === 'grace';
        const daysText = isGrace
            ? `${data.grace_days_left ?? 0} ${window.ui.t('subscription.grace_days_left')}`
            : (data.days_left === null || data.days_left === undefined
                ? '—'
                : `${data.days_left} ${window.ui.t('subscription.days_short')}`);

        const trialBadge = data.is_trial
            ? `<span class="badge badge-new" data-i18n="subscription.trial_badge"></span>`
            : '';

        const graceAlert = isGrace ? `
            <div class="alert-box" style="margin-top:14px;">
                <div style="font-weight:600;" data-i18n="subscription.grace_title"></div>
                <p class="text-sm text-muted" style="margin-top:4px;" data-i18n="subscription.grace_text"></p>
                ${data.grace_end ? `<p class="text-sm font-bold" style="margin-top:6px;">${window.ui.escape(window.ui.t('subscription.grace_deadline'))}: ${window.ui.datetime(data.grace_end)}</p>` : ''}
            </div>` : '';

        container.innerHTML = `
            <div class="card" style="padding:20px;">
                <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;">
                    <div>
                        <div style="font-weight:600;font-size:16px;">${window.ui.escape(data.company_name)}</div>
                        <div class="text-sm text-muted" data-i18n="subscription.page_subtitle"></div>
                    </div>
                    <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                        ${trialBadge}
                        <span class="badge ${badgeClass}">${window.ui.escape(data.subscription_status_display || status)}</span>
                    </div>
                </div>
                ${graceAlert}
                <div class="list-group" style="box-shadow:none;border:1px solid var(--border);margin-top:16px;">
                    <div class="list-row" style="cursor:default;">
                        <span class="text-sm text-muted" data-i18n="subscription.plan"></span>
                        <span class="text-sm font-bold">${window.ui.escape(data.plan_name || '—')}</span>
                    </div>
                    <div class="list-row" style="cursor:default;">
                        <span class="text-sm text-muted" data-i18n="subscription.current_status"></span>
                        <span class="text-sm font-bold">${window.ui.escape(data.subscription_status_display || status)}</span>
                    </div>
                    <div class="list-row" style="cursor:default;">
                        <span class="text-sm text-muted" data-i18n="subscription.start_date"></span>
                        <span class="text-sm font-bold">${data.subscription_start ? window.ui.datetime(data.subscription_start) : '—'}</span>
                    </div>
                    <div class="list-row" style="cursor:default;">
                        <span class="text-sm text-muted" data-i18n="subscription.end_date"></span>
                        <span class="text-sm font-bold">${data.subscription_end ? window.ui.datetime(data.subscription_end) : '—'}</span>
                    </div>
                    <div class="list-row" style="cursor:default;">
                        <span class="text-sm text-muted">${isGrace ? window.ui.t('subscription.grace_deadline') : window.ui.t('subscription.days_left_label')}</span>
                        <span class="text-sm font-bold">${daysText}</span>
                    </div>
                </div>
                <button class="btn ${data.renewal_request_pending ? 'btn-secondary' : 'btn-primary'} btn-block" id="sub-request-renewal"
                        style="margin-top:16px;" ${data.renewal_request_pending ? 'disabled' : ''}
                        data-i18n="${data.renewal_request_pending ? 'subscription.request_pending' : 'subscription.request_renewal'}"></button>
                <p class="text-sm text-muted" style="margin-top:8px;text-align:center;" data-i18n="subscription.renew_hint"></p>
            </div>

            <div class="section-title" data-i18n="subscription.history"></div>
            <div class="list-group" id="sub-history" style="box-shadow:none;border:1px solid var(--border);"></div>
        `;

        container.querySelector('#sub-request-renewal').addEventListener('click', () => this.requestRenewal());

        const historyEl = container.querySelector('#sub-history');
        if (!data.history || !data.history.length) {
            historyEl.innerHTML = `<div class="list-state list-state-empty" data-i18n="companies.no_history"></div>`;
        } else {
            const actionLabels = {
                activated: 'companies.activate', extended: 'companies.extend_30',
                end_set: 'companies.set_end', grace_started: 'subscription.grace_title',
                frozen: 'companies.freeze', unfrozen: 'companies.unfreeze',
                expired: 'companies.subscription_expired',
                plan_changed: 'companies.plan_change',
                cancelled: 'companies.status_cancelled',
            };
            historyEl.innerHTML = data.history.map((h) => `
                <div class="list-row" style="cursor:default;font-size:12px;">
                    <div>
                        <div style="font-weight:600;" data-i18n="${actionLabels[h.action] || 'common.details'}"></div>
                        <div class="text-sm text-muted">
                            ${window.ui.escape(h.actor)} · ${window.ui.datetime(h.created_at)}
                            ${h.days_added ? ` · +${h.days_added} ${window.ui.t('subscription.days_short')}` : ''}
                            ${h.old_plan || h.new_plan ? ` · ${window.ui.escape(h.old_plan || '—')} → ${window.ui.escape(h.new_plan || '—')}` : ''}
                        </div>
                    </div>
                    <div class="text-sm" style="white-space:nowrap;color:var(--text-muted);">
                        ${h.old_status || '—'} → ${h.new_status || '—'}
                    </div>
                </div>`).join('');
        }
        window.i18n.applyTranslations();
    }

    async requestRenewal() {
        try {
            const resp = await window.api.request('/companies/my-subscription/request-renewal/', {
                method: 'POST', body: JSON.stringify({}),
            });
            window.toast.success(window.ui.t(resp.created ? 'subscription.request_sent' : 'subscription.request_already'));
            this.render(this.container);
        } catch (e) {
            window.toast.error(window.ui.errorText ? window.ui.errorText(e) : window.ui.t('common.error'));
        }
    }
}

window.SubscriptionComponent = new SubscriptionComponent();
