/**
 * Подписка (SaaS): статус, срок, тариф, история и запрос продления.
 *
 * Данные: GET /companies/my-subscription/ (owner/admin). Продление в ручном
 * контуре: POST /companies/my-subscription/request-renewal/ создаёт запрос
 * супер-админу (уведомление + push), продлевает он. Используется как модалка
 * (из настроек и с экрана «Подписка истекла») и как страница #/subscription.
 */
const SUBSCRIPTION_BLOCKED_STATUSES = ['expired', 'frozen', 'cancelled'];

// Подписи действий истории — те же ключи, что в companies.js у суперадмина:
// владелец и платформа видят одинаковые названия событий.
const SUBSCRIPTION_ACTION_LABELS = {
    activated: 'companies.activate',
    extended: 'companies.extend_30',
    end_set: 'companies.set_end',
    grace_started: 'subscription.grace_title',
    frozen: 'companies.freeze',
    unfrozen: 'companies.unfreeze',
    expired: 'companies.subscription_expired',
    plan_changed: 'companies.plan_change',
    cancelled: 'companies.status_cancelled',
};

class SubscriptionUI {
    async fetchData() {
        return window.api.request('/companies/my-subscription/');
    }

    changeLabel(h) {
        const labelKey = SUBSCRIPTION_ACTION_LABELS[h.action] || 'common.details';
        const label = window.ui.t(labelKey);
        const who = h.actor && h.actor !== 'system' ? ` · ${h.actor}` : '';
        return `${label}${who}${h.note ? ` — ${h.note}` : ''}`;
    }

    statusBadge(status) {
        if (SUBSCRIPTION_BLOCKED_STATUSES.includes(status)) {
            return '<span class="badge badge-cancel" data-i18n="subscription.frozen"></span>';
        }
        if (status === 'grace') {
            return '<span class="badge badge-progress" data-i18n="subscription.grace_title"></span>';
        }
        return '<span class="badge badge-ready" data-i18n="subscription.active"></span>';
    }

    contentHtml(data) {
        const t = (k, p) => window.ui.t(k, p);
        const blocked = SUBSCRIPTION_BLOCKED_STATUSES.includes(data.subscription_status);
        const isGrace = data.subscription_status === 'grace';

        const historyRows = (data.history || []).map((h) => `
            <div class="list-row u-cursor-default">
                <span class="text-sm">${window.ui.escape(this.changeLabel(h))}</span>
                <span class="text-xs text-muted">${window.ui.escape((h.created_at || '').slice(0, 10))}</span>
            </div>`).join('')
            || '<div class="list-state list-state-empty" data-i18n="common.no_data"></div>';

        const renewBlock = data.renewal_request_pending
            ? '<p class="text-sm" data-i18n="subscription.request_pending"></p>'
            : '<button class="btn btn-primary btn-block u-mt-14" data-sub-renew data-i18n="subscription.request_renewal"></button>';

        return `
            <div class="list-group" style="box-shadow:none;border:1px solid var(--border-color);margin-bottom:14px;">
                <div class="list-row u-cursor-default">
                    <span class="text-sm text-muted" data-i18n="subscription.plan"></span>
                    <span class="text-sm font-bold">${window.ui.escape(data.plan_name || '—')}
                        ${this.statusBadge(data.subscription_status)}
                        ${data.is_trial ? '<span class="badge badge-new" data-i18n="subscription.trial_badge"></span>' : ''}
                    </span>
                </div>
                <div class="list-row u-cursor-default">
                    <span class="text-sm text-muted" data-i18n="subscription.expires"></span>
                    <span class="text-sm font-bold">${window.ui.escape((data.subscription_end || '').slice(0, 10)) || '—'}</span>
                </div>
                <div class="list-row u-cursor-default">
                    <span class="text-sm text-muted" data-i18n="subscription.days_left_label"></span>
                    <span class="text-sm font-bold">${t('subscription.days_left', { days: data.days_left ?? '—' })}</span>
                </div>
                ${isGrace ? `
                <div class="list-row u-cursor-default">
                    <span class="text-sm text-muted" data-i18n="subscription.grace_deadline"></span>
                    <span class="text-sm font-bold">${window.ui.escape((data.grace_end || '').slice(0, 10)) || '—'}</span>
                </div>` : ''}
            </div>
            ${blocked ? '<p class="text-sm text-danger" data-i18n="subscription.frozen_hint"></p>' : ''}
            ${isGrace ? '<p class="text-sm" data-i18n="subscription.grace_text"></p>' : ''}
            ${renewBlock}
            <div class="section-title" data-i18n="subscription.history"></div>
            <div class="list-group u-card-flat-alt">${historyRows}</div>
        `;
    }

    wireActions(root, refresh) {
        const btn = root.querySelector('[data-sub-renew]');
        if (!btn) return;
        btn.addEventListener('click', async () => {
            if (btn.disabled) return;
            btn.disabled = true;
            try {
                const resp = await window.api.request('/companies/my-subscription/request-renewal/', {
                    method: 'POST',
                });
                window.toast.success(window.ui.t(resp.created ? 'subscription.request_sent' : 'subscription.request_already'));
                await refresh();
            } catch (e) {
                btn.disabled = false;
                window.toast.error(window.ui.errorText(e));
            }
        });
    }

    async openModal() {
        const modal = window.ui.modal(
            'subscription.title',
            '<div class="list-state list-state-loading"><span class="spinner"></span></div>',
        );
        const render = async () => {
            try {
                const data = await this.fetchData();
                const body = modal.querySelector('.modal-body');
                body.innerHTML = this.contentHtml(data);
                window.i18n.applyTranslations();
                this.wireActions(body, render);
            } catch (e) {
                window.ui.closeModal(modal);
                window.toast.error(window.ui.errorText(e));
            }
        };
        await render();
    }
}

window.subscriptionUI = new SubscriptionUI();

class SubscriptionComponent {
    async render(container) {
        document.getElementById('page-title').setAttribute('data-i18n', 'subscription.page_title');
        container.innerHTML = `
            <p class="text-sm text-muted" data-i18n="subscription.page_subtitle"></p>
            <div class="card" id="subscription-page-body">
                <div class="list-state list-state-loading"><span class="spinner"></span></div>
            </div>
        `;
        window.i18n.applyTranslations();
        const body = container.querySelector('#subscription-page-body');
        const ui = window.subscriptionUI;
        const render = async () => {
            const data = await ui.fetchData();
            body.innerHTML = ui.contentHtml(data);
            window.i18n.applyTranslations();
            ui.wireActions(body, render);
        };
        await render();
    }
}

window.SubscriptionComponent = new SubscriptionComponent();
