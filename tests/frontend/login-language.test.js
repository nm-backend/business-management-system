/**
 * Экран входа: язык и <html lang>.
 *
 * Проверяем реальные модули, а не копию логики:
 *   - i18n.applyTranslations() синхронизирует <html lang> с выбранным языком;
 *   - api.login() передаёт язык на сервер, но не шлёт его, если человек не
 *     переключал форму (иначе затирался бы язык профиля).
 *
 * Тесты шаблона логина отдельно проверяют, что выбранный язык доходит до
 * api.login(): без этого сервер не узнал бы о выборе.
 */
import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest';

// i18n загружает словари с бэкенда. В юнит-тесте отдаём пустой словарь:
// проверяется переключение языка, а не содержимое locale/*.json.
globalThis.fetch = vi.fn(async () => ({ ok: true, json: async () => ({}) }));

let i18n;
let api;

beforeAll(async () => {
    localStorage.setItem('language', 'uz_cyrl');
    await import('../../static/js/i18n.js');
    await import('../../static/js/api.js');
    i18n = window.i18n;
    api = window.api;
    // Гасим отложенный DOMContentLoaded-инит, чтобы он не сработал посреди теста.
    await i18n.init();
});

beforeEach(() => {
    i18n.currentLang = 'uz_cyrl';
    i18n.translations = {};
    i18n.fallbackTranslations = {};
    document.documentElement.lang = 'uz';
});

describe('<html lang>', () => {
    it('maps internal language codes to BCP-47', () => {
        const cases = [
            ['uz_cyrl', 'uz-Cyrl'],
            ['ru', 'ru'],
            ['ky', 'ky'],
        ];

        for (const [code, expected] of cases) {
            i18n.currentLang = code;
            i18n.applyTranslations();
            expect(document.documentElement.lang).toBe(expected);
        }
    });

    it('updates after switching language', async () => {
        await i18n.setLanguage('ru');

        expect(i18n.currentLang).toBe('ru');
        expect(document.documentElement.lang).toBe('ru');
        expect(localStorage.getItem('language')).toBe('ru');
    });
});

describe('api.login language', () => {
    it('sends the language selected on the login screen', async () => {
        const request = vi.spyOn(api, 'request').mockResolvedValue({
            tokens: { access: 'access', refresh: 'refresh' },
            user: { language: 'ru' },
        });

        await api.login('worker', 'secret', 'ru');

        const [endpoint, options] = request.mock.calls[0];
        expect(endpoint).toBe('/accounts/login/');
        expect(options.noAuth).toBe(true);
        expect(JSON.parse(options.body)).toMatchObject({
            username: 'worker',
            password: 'secret',
            language: 'ru',
        });

        request.mockRestore();
    });

    it('omits language when the form was not changed', async () => {
        const request = vi.spyOn(api, 'request').mockResolvedValue({
            tokens: { access: 'access', refresh: 'refresh' },
            user: { language: 'uz_cyrl' },
        });

        await api.login('worker', 'secret');

        const body = JSON.parse(request.mock.calls[0][1].body);
        expect(body).not.toHaveProperty('language');

        request.mockRestore();
    });
});
