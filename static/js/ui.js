/**
 * UI helpers - общие утилиты фронтенда: модальные окна, форматирование,
 * карты статусов. Все подписи берутся из i18n.
 */
window.ui = {
    /** Переводит ключ через i18n. */
    t(key) {
        return window.i18n.translate(key);
    },

    /** Формат денег: 1250000 -> "1 250 000 сўм". */
    money(value) {
        const num = Number(value || 0);
        return `${num.toLocaleString('ru-RU', { maximumFractionDigits: 0 })} ${this.t('common.currency')}`;
    },

    /** Формат количества без лишних нулей. */
    qty(value) {
        return Number(value || 0).toLocaleString('ru-RU', { maximumFractionDigits: 3 });
    },

    date(value) {
        return value ? new Date(value).toLocaleDateString('ru-RU') : '-';
    },

    datetime(value) {
        return value ? new Date(value).toLocaleString('ru-RU', {
            day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
        }) : '-';
    },

    escape(value) {
        const div = document.createElement('div');
        div.textContent = value ?? '';
        return div.innerHTML;
    },

    /**
     * Открывает модальное окно. bodyHtml - разметка тела,
     * возвращает элемент modal (закрытие: крестик, клик по фону, ui.closeModal).
     */
    modal(titleKey, bodyHtml) {
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content" role="dialog" aria-modal="true">
                <div class="modal-header">
                    <h3 data-i18n="${titleKey}"></h3>
                    <button class="close" type="button" aria-label="Close">&times;</button>
                </div>
                <div class="modal-body">${bodyHtml}</div>
            </div>`;
        modal.querySelector('.close').addEventListener('click', () => modal.remove());
        modal.addEventListener('click', (e) => { if (e.target === modal) modal.remove(); });
        document.body.appendChild(modal);
        window.i18n.applyTranslations();
        return modal;
    },

    /** Кнопка отправки формы: блокирует на время запроса. */
    async submitGuard(button, action) {
        button.disabled = true;
        try {
            await action();
        } finally {
            button.disabled = false;
        }
    },

    /** Бейдж статуса заказа. */
    orderBadge(status) {
        const map = {
            new: 'badge-new', awaiting_material: 'badge-cancel',
            sent_to_worker: 'badge-progress', accepted: 'badge-progress',
            worker_refused: 'badge-cancel', in_progress: 'badge-progress',
            awaiting_confirmation: 'badge-progress', ready: 'badge-ready',
            delivered: 'badge-ready', cancelled: 'badge-cancel',
        };
        const cls = map[status] || 'badge-new';
        return `<span class="badge ${cls}" data-i18n="statuses.${status}"></span>`;
    },

    /** Бейдж статуса оплаты. */
    paymentBadge(status) {
        const map = { unpaid: 'badge-cancel', partial: 'badge-progress', paid: 'badge-ready' };
        return `<span class="badge ${map[status] || 'badge-new'}" data-i18n="payment_statuses.${status}"></span>`;
    },

    /** Бейдж статуса задачи/работы. */
    workBadge(status) {
        const map = {
            pending: 'badge-progress', accepted: 'badge-new', refused: 'badge-cancel',
            in_progress: 'badge-progress', completed: 'badge-progress',
            awaiting_confirmation: 'badge-progress',
            confirmed: 'badge-ready', rejected: 'badge-cancel', cancelled: 'badge-cancel',
        };
        return `<span class="badge ${map[status] || 'badge-new'}" data-i18n="work_statuses.${status}"></span>`;
    },

    /** Человекочитаемый текст первой ошибки из ответа DRF. */
    errorText(error) {
        const data = error?.data || {};
        if (typeof data.detail === 'string') return data.detail;
        const firstKey = Object.keys(data)[0];
        const value = firstKey ? data[firstKey] : null;
        const text = Array.isArray(value) ? value[0] : value;
        return (typeof text === 'string' && text) || this.t('common.error');
    },

    /** <option> для единиц измерения. */
    unitOptions(selected) {
        return ['sht', 'm', 'm2', 'izdelie']
            .map((u) => `<option value="${u}" ${u === selected ? 'selected' : ''} data-i18n="units.${u}"></option>`)
            .join('');
    },
};
