/**
 * Произвольный период отчёта (ТЗ §18 / макет «хусусий»).
 *
 * Хелперы берутся из РЕАЛЬНОГО static/js/ui.js. Контракт SPA — из
 * finance.js и dashboard.js: custom не уходит на API как period=custom
 * (неизвестный пресет на сервере молча становится «месяц»).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const uiSource = readFileSync(resolve(here, '../../static/js/ui.js'), 'utf-8');
const financeSource = readFileSync(resolve(here, '../../static/js/components/finance.js'), 'utf-8');
const dashboardSource = readFileSync(resolve(here, '../../static/js/components/dashboard.js'), 'utf-8');

beforeEach(() => {
    window.i18n = { translate: (key) => key, applyTranslations: () => {} };
    window.toast = { error: vi.fn(), success: () => {}, info: () => {} };
    // IIFE в конце ui.js вешают MutationObserver — в vitest eval это шум.
    const helpers = uiSource.slice(0, uiSource.indexOf('(function reportValidationErrors'));
    // eslint-disable-next-line no-eval
    eval(helpers);
});

describe('ui.isIsoDate / reportPeriodError', () => {
    it('принимает календарную YYYY-MM-DD и отвергает несуществующие дни', () => {
        expect(window.ui.isIsoDate('2026-08-01')).toBe(true);
        expect(window.ui.isIsoDate('2026-02-29')).toBe(false);
        expect(window.ui.isIsoDate('2024-02-29')).toBe(true);
        expect(window.ui.isIsoDate('01.08.2026')).toBe(false);
        expect(window.ui.isIsoDate('2026-8-1')).toBe(false);
        expect(window.ui.isIsoDate('')).toBe(false);
    });

    it('требует обе даты и порядок start ≤ end', () => {
        expect(window.ui.reportPeriodError('', '2026-08-10')).toBe('periods.custom_both_required');
        expect(window.ui.reportPeriodError('2026-08-01', '')).toBe('periods.custom_both_required');
        expect(window.ui.reportPeriodError('2026-13-01', '2026-08-10')).toBe('periods.custom_invalid');
        expect(window.ui.reportPeriodError('2026-08-10', '2026-08-01')).toBe('periods.custom_order');
        expect(window.ui.reportPeriodError('2026-08-01', '2026-08-01')).toBeNull();
        expect(window.ui.reportPeriodError('2026-08-01', '2026-08-10')).toBeNull();
    });
});

describe('ui.reportPeriodQuery', () => {
    it('для custom шлёт только date_from и date_to, без period=custom', () => {
        const built = window.ui.reportPeriodQuery({
            period: 'custom',
            dateFrom: '2026-08-01',
            dateTo: '2026-08-10',
        });
        expect(built.error).toBeNull();
        expect(built.query).toBe('date_from=2026-08-01&date_to=2026-08-10');
        expect(built.query).not.toMatch(/period=/);
    });

    it('для пресетов шлёт period= и не считает границы на фронте', () => {
        for (const period of ['today', 'yesterday', 'week', 'month', 'quarter', 'year']) {
            const built = window.ui.reportPeriodQuery({ period });
            expect(built.error).toBeNull();
            expect(built.query).toBe(`period=${period}`);
        }
    });

    it('неизвестный пресет безопасен: month, а не custom', () => {
        const built = window.ui.reportPeriodQuery({ period: 'хусусий' });
        expect(built.query).toBe('period=month');
    });

    it('custom без дат — ошибка, пустой query', () => {
        const built = window.ui.reportPeriodQuery({ period: 'custom' });
        expect(built.error).toBe('periods.custom_both_required');
        expect(built.query).toBe('');
    });
});

describe('ui.formatIsoDate — без сдвига timezone', () => {
    it('форматирует календарную дату, не через Date.parse UTC', () => {
        expect(window.ui.formatIsoDate('2026-08-01')).toBe('01.08.2026');
        expect(window.ui.formatIsoDate('2026-08-01T23:59:00Z')).toBe('01.08.2026');
        expect(window.ui.reportPeriodRangeText('2026-08-01', '2026-08-10')).toBe('01.08.2026 – 10.08.2026');
    });
});

describe('ui.bindReportPeriodControls', () => {
    it('custom → пресет сбрасывает даты; apply читает инпуты', () => {
        document.body.innerHTML = `
            <button data-period="month">month</button>
            <button data-period="custom">custom</button>
            <input id="period-date-from" value="2026-08-01">
            <input id="period-date-to" value="2026-08-10">
            <button id="period-apply">ok</button>
        `;
        const component = { period: 'custom', dateFrom: '2026-07-01', dateTo: '2026-07-31' };
        const reload = vi.fn();
        window.ui.bindReportPeriodControls(document.body, component, reload);

        document.querySelector('[data-period="month"]').click();
        expect(component.period).toBe('month');
        expect(component.dateFrom).toBe('');
        expect(component.dateTo).toBe('');
        expect(reload).toHaveBeenCalledTimes(1);

        component.period = 'custom';
        document.querySelector('#period-date-from').value = '2026-08-01';
        document.querySelector('#period-date-to').value = '2026-08-10';
        document.querySelector('#period-apply').click();
        expect(component.dateFrom).toBe('2026-08-01');
        expect(component.dateTo).toBe('2026-08-10');
        expect(reload).toHaveBeenCalledTimes(2);
        expect(window.toast.error).not.toHaveBeenCalled();
    });

    it('apply без дат не перезагружает и показывает тост', () => {
        document.body.innerHTML = `
            <input id="period-date-from" value="">
            <input id="period-date-to" value="">
            <button id="period-apply">ok</button>
        `;
        const component = { period: 'custom', dateFrom: '', dateTo: '' };
        const reload = vi.fn();
        window.ui.bindReportPeriodControls(document.body, component, reload);
        document.querySelector('#period-apply').click();
        expect(reload).not.toHaveBeenCalled();
        expect(window.toast.error).toHaveBeenCalledWith('periods.custom_both_required');
    });
});

describe('SPA: finance и dashboard используют тот же query', () => {
    it('финансы: вкладка custom, экспорт через reportPeriodQuery, без period=custom', () => {
        expect(financeSource).toMatch(/'custom'/);
        expect(financeSource).toMatch(/reportPeriodQuery/);
        expect(financeSource).toMatch(/customPeriodPanelHtml/);
        expect(financeSource).toMatch(/export\/finance\/\?\$\{built\.query\}/);
        expect(financeSource).not.toMatch(/period=\$\{period\}/);
        expect(financeSource).not.toMatch(/period=custom/);
        expect(financeSource).toMatch(/periods\.selected_range/);
    });

    it('дашборд владельца: custom + date_from/date_to, без вчерашнего пресета как новой фичи', () => {
        expect(dashboardSource).toMatch(/\['today', 'week', 'month', 'quarter', 'year', 'custom'\]/);
        expect(dashboardSource).toMatch(/reportPeriodQuery/);
        expect(dashboardSource).toMatch(/customPeriodPanelHtml/);
        expect(dashboardSource).not.toMatch(/period=\$\{period\}/);
        expect(dashboardSource).not.toMatch(/period=custom/);
        expect(dashboardSource).toMatch(/analytics\/owner\/\?\$\{built\.query\}/);
    });
});
