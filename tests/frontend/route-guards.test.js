/**
 * Ролевая защита маршрутов SPA.
 *
 * Найдено аудитом: все маршруты регистрировались всем ролям. Пункты меню роль
 * не видела, но по прямому адресу (#/finance у работника) страница
 * открывалась и начинала обращаться к закрытым эндпоинтам — вместо честного
 * «нет доступа» пользователь получал сломанный экран с ошибками.
 *
 * Тест разбирает РЕАЛЬНЫЙ static/js/app.js: он проверяет не копию логики, а
 * тот же список маршрутов и ролей, который выполняется в браузере. Если
 * кто-то добавит маршрут без защиты или расширит список ролей у финансов,
 * тест упадёт.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const appSource = readFileSync(resolve(here, '../../static/js/app.js'), 'utf-8');

/** Достаёт из app.js карту «маршрут -> разрешённые роли». */
function parseGuardedRoutes(source) {
    const routes = {};
    const re = /addGuardedRoute\(\s*'([^']+)'\s*,\s*[^,]+,\s*(null|\[[^\]]*\])\s*\)/g;
    let match;
    while ((match = re.exec(source)) !== null) {
        const [, path, roles] = match;
        routes[path] = roles === 'null'
            ? null
            : roles.slice(1, -1).split(',').map((r) => r.trim().replace(/'/g, '')).filter(Boolean);
    }
    return routes;
}

const routes = parseGuardedRoutes(appSource);

/** Повторяет решение addGuardedRoute для конкретной роли. */
function isAllowed(path, role) {
    const allowed = routes[path];
    if (allowed === undefined) return undefined; // маршрут не зарегистрирован
    return allowed === null || allowed.includes(role);
}

describe('ролевая защита маршрутов SPA', () => {
    it('все бизнес-маршруты зарегистрированы через addGuardedRoute', () => {
        for (const path of ['/', '/warehouse', '/finished-products', '/clients',
            '/orders', '/orders/kanban', '/production', '/finance',
            '/messages', '/subscription', '/settings', '/audit', '/backup']) {
            expect(routes[path], `маршрут ${path} без ролевой защиты`).not.toBe(undefined);
        }
    });

    it('незащищённых addRoute для бизнес-ролей не осталось', () => {
        // Разрешён только блок супер-администратора: там свой список маршрутов.
        const superadminBlock = appSource.split('// SuperAdmin routes')[1] || '';
        const businessPart = appSource.replace(superadminBlock, '');
        expect(businessPart).not.toMatch(/window\.router\.addRoute\('\/finance'/);
        expect(businessPart).not.toMatch(/window\.router\.addRoute\('\/audit'/);
        expect(businessPart).not.toMatch(/window\.router\.addRoute\('\/clients'/);
    });

    it('финансы доступны только владельцу', () => {
        expect(isAllowed('/finance', 'owner')).toBe(true);
        expect(isAllowed('/finance', 'admin')).toBe(false);
        expect(isAllowed('/finance', 'worker')).toBe(false);
        expect(isAllowed('/finance', 'manager')).toBe(false);
    });

    it('журнал аудита и резервные копии — только владельцу', () => {
        for (const path of ['/audit', '/backup']) {
            expect(isAllowed(path, 'owner')).toBe(true);
            expect(isAllowed(path, 'admin')).toBe(false);
            expect(isAllowed(path, 'worker')).toBe(false);
        }
    });

    it('клиенты закрыты от работника, открыты владельцу и администратору', () => {
        expect(isAllowed('/clients', 'owner')).toBe(true);
        expect(isAllowed('/clients', 'admin')).toBe(true);
        expect(isAllowed('/clients', 'manager')).toBe(true);
        expect(isAllowed('/clients', 'worker')).toBe(false);
    });

    it('подписка — владельцу и администратору', () => {
        expect(isAllowed('/subscription', 'owner')).toBe(true);
        expect(isAllowed('/subscription', 'admin')).toBe(true);
        expect(isAllowed('/subscription', 'worker')).toBe(false);
    });

    it('рабочие экраны доступны всем ролям', () => {
        for (const path of ['/', '/warehouse', '/production', '/messages', '/settings']) {
            for (const role of ['owner', 'admin', 'worker']) {
                expect(isAllowed(path, role), `${path} для ${role}`).toBe(true);
            }
        }
    });

    it('запрещённый маршрут рисует 403, а не компонент раздела', () => {
        expect(appSource).toMatch(/forbiddenRoute/);
        expect(appSource).toMatch(/eyebrow">403/);
        expect(appSource).toMatch(/data-i18n="common.forbidden"/);
    });
});
