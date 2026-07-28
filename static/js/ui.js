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
        // Экранируем и кавычки: значение может подставляться в value="..." формы.
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
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
        const close = () => this.closeModal(modal);
        modal.querySelector('.close').addEventListener('click', close);
        modal.addEventListener('click', (e) => { if (e.target === modal) close(); });
        document.body.appendChild(modal);

        // Окно занимает СВОЮ запись в истории (адрес не меняется). Тогда «Назад»
        // на телефоне закрывает карточку, а не уводит на другую страницу.
        // Раньше «Назад» менял хеш: страница под окном перерисовывалась, а само
        // окно оставалось висеть поверх чужого экрана (воспроизведено: открыт
        // заказ на #/orders, «Назад» -> #/settings, окно на месте).
        history.pushState({ skpModal: true }, '', location.href);
        modal.dataset.skpHistory = '1';

        window.i18n.applyTranslations();
        // Фокус внутрь окна: Tab не должен уходить на страницу под ним.
        const focusable = modal.querySelector('input, select, textarea, button:not(.close)');
        if (focusable) focusable.focus();
        return modal;
    },

    /** Закрывает окно, освобождая занятую им запись истории. */
    closeModal(modal) {
        if (!modal || modal.dataset.skpClosing) return;
        modal.dataset.skpClosing = '1';
        const ownsHistoryEntry = modal.dataset.skpHistory === '1';
        modal.remove();
        if (ownsHistoryEntry && history.state && history.state.skpModal) history.back();
    },

    /**
     * Закрывает верхнее окно БЕЗ обращения к истории.
     * Вызывается из роутера, когда назад/переход уже произошёл.
     */
    closeTopModal() {
        const modals = document.querySelectorAll('.modal');
        if (!modals.length) return false;
        const top = modals[modals.length - 1];
        top.dataset.skpHistory = '';   // запись истории уже израсходована
        top.dataset.skpClosing = '1';
        top.remove();
        return true;
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

    /**
     * Карточка показателя: SVG-иконка, заголовок, значение и (опционально) %.
     * opts: { icon (SVG string or emoji), color, titleKey, value, delta, id, href }
     */
    statCard(opts) {
        let deltaHtml = '';
        if (opts.delta !== undefined && opts.delta !== null) {
            const dir = opts.delta > 0 ? 'up' : (opts.delta < 0 ? 'down' : 'flat');
            const arrow = opts.delta > 0 ? '↑' : (opts.delta < 0 ? '↓' : '→');
            deltaHtml = `<span class="stat-delta ${dir}">${arrow} ${Math.abs(opts.delta)}%</span>`;
        }
        const cls = `stat-card${opts.id || opts.href ? ' clickable' : ''}`;
        const idAttr = opts.id ? ` id="${opts.id}"` : '';
        const tag = opts.href ? 'a' : 'div';
        const hrefAttr = opts.href ? ` href="${opts.href}" style="text-decoration:none;color:inherit;"` : '';
        const iconHtml = opts.icon && opts.icon.startsWith('<svg')
            ? opts.icon
            : (opts.icon || window.icon('activity', 18));
        return `<${tag} class="${cls}"${idAttr}${hrefAttr}>
            <div class="stat-icon ${opts.color || 'blue'}">${iconHtml}</div>
            <div class="stat-body">
                <div class="stat-title" data-i18n="${opts.titleKey}"></div>
                <div class="stat-value ${opts.valueClass || ''}">${opts.value}</div>
            </div>
            ${deltaHtml}
        </${tag}>`;
    },

    /**
     * Пончиковая диаграмма (inline SVG, без внешних библиотек).
     * segments: [{ label, value, color }]. Возвращает разметку графика + легенды.
     */
    donutChart(segments, opts = {}) {
        const palette = ['#1c64d9', '#16a34a', '#f59e0b', '#8b5cf6', '#e5484d', '#0ea5e9', '#64748b', '#ec4899'];
        const data = (segments || []).filter((s) => Number(s.value) > 0);
        const total = data.reduce((sum, s) => sum + Number(s.value), 0);
        if (!total) {
            return `<div class="list-state list-state-empty" data-i18n="common.no_data"></div>`;
        }
        const r = 60, c = 2 * Math.PI * r, cx = 80, cy = 80;
        let offset = 0;
        const arcs = data.map((s, i) => {
            const frac = Number(s.value) / total;
            const color = s.color || palette[i % palette.length];
            const dash = `${(frac * c).toFixed(2)} ${(c - frac * c).toFixed(2)}`;
            const circle = `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${color}" stroke-width="22" stroke-dasharray="${dash}" stroke-dashoffset="${(-offset * c).toFixed(2)}" transform="rotate(-90 ${cx} ${cy})"></circle>`;
            offset += frac;
            return circle;
        }).join('');
        const legend = data.map((s, i) => {
            const color = s.color || palette[i % palette.length];
            const pct = Math.round((Number(s.value) / total) * 100);
            return `<div class="donut-legend-row">
                <span class="donut-dot" style="background:${color}"></span>
                <span class="donut-label">${this.escape(s.label)}</span>
                <span class="donut-pct">${pct}%</span>
            </div>`;
        }).join('');
        return `<div class="donut-wrap">
            <svg class="donut-svg" viewBox="0 0 160 160" width="150" height="150" aria-hidden="true">
                ${arcs}
                <text x="80" y="76" text-anchor="middle" class="donut-center-num">${data.length}</text>
                <text x="80" y="94" text-anchor="middle" class="donut-center-lbl">${this.escape(opts.centerLabel || '')}</text>
            </svg>
            <div class="donut-legend">${legend}</div>
        </div>`;
    },

    /** Дебаунс для оптимизации обработчиков ввода (поиск и т.д.) */
    debounce(fn, wait = 300) {
        let timeout;
        return function (...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => fn.apply(this, args), wait);
        };
    },

    /** Сжатие изображений на стороне клиента перед отправкой (для работы в цеху при плохом 3G/4G). */
    async compressImage(file, maxWidth = 1280, maxHeight = 1280, quality = 0.8) {
        if (!file || !file.type.startsWith('image/')) return file;
        return new Promise((resolve) => {
            const img = new Image();
            const url = URL.createObjectURL(file);
            img.onload = () => {
                URL.revokeObjectURL(url);
                let { width, height } = img;
                if (width > maxWidth || height > maxHeight) {
                    if (width > height) {
                        height = Math.round((height * maxWidth) / width);
                        width = maxWidth;
                    } else {
                        width = Math.round((width * maxHeight) / height);
                        height = maxHeight;
                    }
                }
                const canvas = document.createElement('canvas');
                canvas.width = width;
                canvas.height = height;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0, width, height);
                canvas.toBlob((blob) => {
                    if (!blob) return resolve(file);
                    const compressedFile = new File([blob], file.name, {
                        type: 'image/jpeg',
                        lastModified: Date.now()
                    });
                    resolve(compressedFile);
                }, 'image/jpeg', quality);
            };
            img.onerror = () => resolve(file);
            img.src = url;
        });
    },
};
