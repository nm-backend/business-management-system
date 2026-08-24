/**
 * Подписка (SaaS billing): модалка для владельца — статус, срок, тарифы,
 * история, продление; используется из настроек и с экрана «Подписка истекла».
 *
 * Данные: GET /billing/subscription/ (owner). Продление создаёт счёт через
 * payment adapter; пока провайдер manual — счёт ждёт подтверждения
 * супер-админа, после чего подписка продлевается автоматически.
 */
class SubscriptionUI {
    async openModal() {
        const modal = window.ui.modal(
            'subscription.title',
            '<div class="list-state list-state-loading"><span class="spinner"></span></div>',
        );
        try {
            const data = await window.api.request('/billing/subscription/');
            this.render(modal, data);
        } catch (e) {
            window.ui.closeModal(modal);
            window.toast.error(window.ui.errorText(e));
        }
    }

    render(modal, data) {
        const body = modal.querySelector('.modal-body');
        const t = (k, p) => window.ui.t(k, p);
        const statusBadge = data.is_blocked
            ? '<span class="badge badge-cancel" data-i18n="subscription.frozen"></span>'
            : '<span class="badge badge-ready" data-i18n="subscription.active"></span>';

        const historyRows = (data.history || []).map((ev) => `
            <div class="list-row" style="cursor:default;">
                <span class="text-sm">${window.ui.escape(this.eventLabel(ev))}</span>
                <span class="text-xs text-muted">${window.ui.escape((ev.created_at || '').slice(0, 10))}</span>
            </div>`).join('')
            || '<div class="list-state list-state-empty" data-i18n="common.no_data"></div>';

        const planOptions = (data.plans || []).map((p) => `
            <label class="list-row" style="cursor:pointer;">
                <span>
                    <span class="font-bold">${window.ui.escape(p.label)}</span>
                    ${p.note ? `<span class="text-sm text-muted"> · ${window.ui.escape(p.note)}</span>` : ''}
                </span>
                <input type="radio" name="sub-plan" value="${window.ui.escape(p.key)}" ${p.key === data.plan ? 'checked' : ''}>
            </label>`).join('');

        const pendingInvoice = (data.invoices || []).find((i) => i.status === 'pending');

        body.innerHTML = `
            <div class="list-group" style="box-shadow:none;border:1px solid var(--border-color);margin-bottom:14px;">
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm text-muted" data-i18n="subscription.plan"></span>
                    <span class="text-sm font-bold">${window.ui.escape(data.plan)} ${statusBadge}</span>
                </div>
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm text-muted" data-i18n="subscription.expires"></span>
                    <span class="text-sm font-bold">${window.ui.escape((data.expires_at || '').slice(0, 10)) || '—'}</span>
                </div>
                <div class="list-row" style="cursor:default;">
                    <span class="text-sm text-muted" data-i18n="subscription.days_left_label"></span>
                    <span class="text-sm font-bold">${t('subscription.days_left', { days: data.days_left })}</span>
                </div>
            </div>
            ${data.is_blocked ? '<p class="text-sm text-danger" data-i18n="subscription.frozen_hint"></p>' : ''}
            ${pendingInvoice ? `<p class="text-sm" data-i18n="subscription.invoice_pending"></p>` : ''}
            <div class="section-title" data-i18n="subscription.choose_plan"></div>
            <div class="list-group" style="box-shadow:none;border:1px solid var(--border-color);">${planOptions}</div>
            <button class="btn btn-primary btn-block" id="subscription-renew" style="margin-top:14px;" data-i18n="subscription.renew"></button>
            <div class="section-title" data-i18n="subscription.history"></div>
            <div class="list-group" style="box-shadow:none;border:1px solid var(--border-color);">${historyRows}</div>
        `;
        window.i18n.applyTranslations();

        const renewBtn = body.querySelector('#subscription-renew');
        renewBtn.addEventListener('click', () => this.renew(modal, data, renewBtn));
    }

    eventLabel(ev) {
        const action = window.ui.t(`subscription.event.${ev.action}`);
        const who = ev.actor_name && ev.actor_name !== 'system'
            ? ` · ${ev.actor_name}` : '';
        return `${action}${who}${ev.note ? ` — ${ev.note}` : ''}`;
    }

    async renew(modal, data, btn) {
        if (btn.disabled) return;
        btn.disabled = true;
        const plan = (modal.querySelector('input[name="sub-plan"]:checked') || {}).value || data.plan;
        try {
            await window.api.request('/billing/subscription/renew/', {
                method: 'POST',
                body: JSON.stringify({ plan }),
            });
            window.toast.success(window.ui.t('subscription.renew_requested'));
            const fresh = await window.api.request('/billing/subscription/');
            this.render(modal, fresh);
        } catch (e) {
            btn.disabled = false;
            window.toast.error(window.ui.errorText(e));
        }
    }
}

window.subscriptionUI = new SubscriptionUI();
