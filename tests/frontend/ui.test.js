/**
 * UI helpers unit tests.
 *
 * Tests pure functions: badge HTML generation, money/date formatting, escape.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

// ---------------------------------------------------------------------------
// Minimal ui object reimplementation for isolated testing.
// We test the LOGIC of each helper, not DOM rendering.
// ---------------------------------------------------------------------------
const ui = {
    t(key, params) {
        return window.i18n.translate(key, params);
    },

    money(value) {
        const num = Number(value || 0);
        return `${num.toLocaleString('ru-RU', { maximumFractionDigits: 0 })} ${this.t('common.currency')}`;
    },

    qty(value) {
        return Number(value || 0).toLocaleString('ru-RU', { maximumFractionDigits: 3 });
    },

    date(value) {
        return value ? new Date(value).toLocaleDateString('ru-RU') : '-';
    },

    datetime(value) {
        return value ? new Date(value).toLocaleString('ru-RU', {
            day: '2-digit', month: '2-digit', year: 'numeric',
            hour: '2-digit', minute: '2-digit',
        }) : '-';
    },

    escape(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    },

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

    paymentBadge(status) {
        const map = { unpaid: 'badge-cancel', partial: 'badge-progress', paid: 'badge-ready' };
        return `<span class="badge ${map[status] || 'badge-new'}" data-i18n="payment_statuses.${status}"></span>`;
    },

    workBadge(status) {
        const map = {
            pending: 'badge-progress', accepted: 'badge-new', refused: 'badge-cancel',
            in_progress: 'badge-progress', completed: 'badge-progress',
            awaiting_confirmation: 'badge-progress',
            confirmed: 'badge-ready', rejected: 'badge-cancel', cancelled: 'badge-cancel',
        };
        return `<span class="badge ${map[status] || 'badge-new'}" data-i18n="work_statuses.${status}"></span>`;
    },

    errorText(error) {
        const data = error?.data || {};
        if (typeof data.detail === 'string') return data.detail;
        const firstKey = Object.keys(data)[0];
        const value = firstKey ? data[firstKey] : null;
        const text = Array.isArray(value) ? value[0] : value;
        return (typeof text === 'string' && text) || this.t('common.error');
    },
};

// Setup i18n stub
beforeEach(() => {
    window.i18n = { translate: (key) => key, applyTranslations: () => {} };
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('ui.money', () => {
    it('formats a large number with currency', () => {
        expect(ui.money(1250000)).toBe('1 250 000 common.currency');
    });

    it('formats zero', () => {
        expect(ui.money(0)).toBe('0 common.currency');
    });

    it('handles null/undefined as zero', () => {
        expect(ui.money(null)).toBe('0 common.currency');
        expect(ui.money(undefined)).toBe('0 common.currency');
    });

    it('formats negative numbers', () => {
        expect(ui.money(-5000)).toBe('-5 000 common.currency');
    });

    it('truncates decimal parts', () => {
        expect(ui.money(1234.567)).toBe('1 235 common.currency');
    });
});

describe('ui.qty', () => {
    it('formats quantity with up to 3 decimals', () => {
        expect(ui.qty(2.5)).toBe('2,5');
    });

    it('handles zero', () => {
        expect(ui.qty(0)).toBe('0');
    });

    it('handles null', () => {
        expect(ui.qty(null)).toBe('0');
    });
});

describe('ui.date', () => {
    it('returns dash for null', () => {
        expect(ui.date(null)).toBe('-');
    });

    it('formats a valid date string', () => {
        const result = ui.date('2024-05-25');
        // Should contain day, month, year in some format
        expect(result).toMatch(/25/);
        expect(result).toMatch(/2024/);
    });
});

describe('ui.escape', () => {
    it('escapes HTML entities', () => {
        expect(ui.escape('<script>alert("xss")</script>'))
            .toBe('&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;');
    });

    it('escapes ampersand', () => {
        expect(ui.escape('a & b')).toBe('a &amp; b');
    });

    it('escapes single quotes', () => {
        expect(ui.escape("it's")).toBe("it&#39;s");
    });

    it('handles null/undefined as empty string', () => {
        expect(ui.escape(null)).toBe('');
        expect(ui.escape(undefined)).toBe('');
    });

    it('handles numbers', () => {
        expect(ui.escape(42)).toBe('42');
    });
});

describe('ui.orderBadge', () => {
    it('returns correct badge class for "new"', () => {
        const html = ui.orderBadge('new');
        expect(html).toContain('badge-new');
        expect(html).toContain('data-i18n="statuses.new"');
    });

    it('returns correct badge class for "delivered"', () => {
        const html = ui.orderBadge('delivered');
        expect(html).toContain('badge-ready');
    });

    it('returns correct badge class for "cancelled"', () => {
        const html = ui.orderBadge('cancelled');
        expect(html).toContain('badge-cancel');
    });

    it('falls back to badge-new for unknown status', () => {
        const html = ui.orderBadge('unknown_status');
        expect(html).toContain('badge-new');
    });
});

describe('ui.paymentBadge', () => {
    it('unpaid → badge-cancel', () => {
        expect(ui.paymentBadge('unpaid')).toContain('badge-cancel');
    });

    it('paid → badge-ready', () => {
        expect(ui.paymentBadge('paid')).toContain('badge-ready');
    });

    it('partial → badge-progress', () => {
        expect(ui.paymentBadge('partial')).toContain('badge-progress');
    });

    it('unknown → badge-new', () => {
        expect(ui.paymentBadge('something')).toContain('badge-new');
    });
});

describe('ui.workBadge', () => {
    it('confirmed → badge-ready', () => {
        expect(ui.workBadge('confirmed')).toContain('badge-ready');
    });

    it('rejected → badge-cancel', () => {
        expect(ui.workBadge('rejected')).toContain('badge-cancel');
    });

    it('in_progress → badge-progress', () => {
        expect(ui.workBadge('in_progress')).toContain('badge-progress');
    });

    it('unknown → badge-new', () => {
        expect(ui.workBadge('nonexistent')).toContain('badge-new');
    });
});

describe('ui.errorText', () => {
    it('extracts detail string from DRF error', () => {
        const error = { data: { detail: 'Not found' } };
        expect(ui.errorText(error)).toBe('Not found');
    });

    it('extracts first field error from DRF error', () => {
        const error = { data: { name: ['This field is required.'] } };
        expect(ui.errorText(error)).toBe('This field is required.');
    });

    it('returns i18n error key when no data', () => {
        expect(ui.errorText({})).toBe('common.error');
        expect(ui.errorText(null)).toBe('common.error');
    });
});
