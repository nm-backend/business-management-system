/**
 * Удаление компании: модалка и запрос.
 *
 * Проверяем реальный CompaniesComponent, а не копию логики:
 *   - кнопка отправки включается только при точном названии (NFC, пробелы);
 *   - запрос идёт POST-ом на action-эндпоинт с confirm_name;
 *   - после успеха закрываются обе модалки и список перезагружается.
 */
import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest';

let component;
let modal;

beforeAll(async () => {
    window.i18n = {
        currentLang: 'uz_cyrl',
        translate: (key, params) => {
            if (key === 'companies.delete_warning') return `«${params.name}»`;
            return key;
        },
        applyTranslations: vi.fn(),
    };
    window.ui = {
        modal: vi.fn((titleKey, bodyHtml) => {
            modal = document.createElement('div');
            modal.innerHTML = `<h3>${titleKey}</h3>${bodyHtml}`;
            document.body.appendChild(modal);
            return modal;
        }),
        t: (key) => key,
        errorText: (error) => error?.message || 'error',
        submitGuard: async (button, action) => {
            button.disabled = true;
            try {
                return await action();
            } finally {
                button.disabled = false;
            }
        },
        closeModal: vi.fn((element) => element?.remove()),
    };
    window.api = { request: vi.fn().mockResolvedValue({}) };
    window.toast = { success: vi.fn(), error: vi.fn() };
    await import('../../static/js/components/companies.js');
    component = window.CompaniesComponent;
});

beforeEach(() => {
    document.body.innerHTML = '';
    window.api.request.mockClear();
    window.ui.closeModal.mockClear();
    window.toast.success.mockClear();
    component.companies = [{ id: 7, name: 'Acme' }];
    component.page = 1;
    component.loadCompanies = vi.fn().mockResolvedValue();
    component.loadStats = vi.fn();
});

describe('company deletion modal', () => {
    it('normalizes NFC and repeated spaces but keeps case', () => {
        expect(component.normalizeCompanyName('  Acme  ')).toBe('Acme');
        expect(component.normalizeCompanyName('Cafe\u0301')).toBe('Caf\u00e9');
        expect(component.normalizeCompanyName('acme')).not.toBe('Acme');
    });

    it('sends POST with confirm_name and refreshes the list', async () => {
        component.openDeleteModal({ id: 7, name: 'Acme' }, { remove: vi.fn() });
        const input = modal.querySelector('#delete-company-name');
        const submit = modal.querySelector('#delete-company-submit');
        const form = modal.querySelector('#delete-company-form');

        expect(submit.disabled).toBe(true);
        input.value = '  Acme  ';
        input.dispatchEvent(new Event('input'));
        expect(submit.disabled).toBe(false);

        form.dispatchEvent(new Event('submit', { cancelable: true }));
        await new Promise((resolve) => setTimeout(resolve, 0));

        expect(window.api.request).toHaveBeenCalledWith('/companies/7/delete/', {
            method: 'POST',
            body: JSON.stringify({ confirm_name: '  Acme  ' }),
        });
        expect(component.loadCompanies).toHaveBeenCalled();
        expect(window.toast.success).toHaveBeenCalled();
    });
});
