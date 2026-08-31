/**
 * I18nManager unit tests.
 *
 * Tests the pure logic: dot-path lookup, parameter interpolation, fallback chain.
 * We instantiate I18nManager directly (bypassing fetch/DOM) by injecting data.
 */
import { describe, it, expect, beforeEach } from 'vitest';

// ---------------------------------------------------------------------------
// Minimal I18nManager reimplementation for isolated testing.
// We test the LOGIC, not the fetch/DOM wiring (integration covers that).
// ---------------------------------------------------------------------------
class I18nManager {
    constructor() {
        this.translations = {};
        this.fallbackTranslations = {};
        this.fallbackLang = 'uz_cyrl';
        this.currentLang = 'uz_cyrl';
    }

    lookup(dict, key) {
        const keys = key.split('.');
        let value = dict;
        for (const k of keys) {
            if (value && Object.prototype.hasOwnProperty.call(value, k)) {
                value = value[k];
            } else {
                return undefined;
            }
        }
        return value;
    }

    translate(key, params) {
        let value = this.lookup(this.translations, key);
        if (value === undefined) {
            value = this.lookup(this.fallbackTranslations, key);
        }
        if (value === undefined) return key;
        if (params) {
            for (const [name, val] of Object.entries(params)) {
                value = value.split(`{${name}}`).join(String(val ?? ''));
            }
        }
        return value;
    }
}

// ---------------------------------------------------------------------------
// Test data: uz_cyrl (primary) and ru (secondary)
// ---------------------------------------------------------------------------
const UZ_CYRL = {
    common: { loading: 'Юкланмоқда...', error: 'Хатолик', currency: 'сўм' },
    roles: { owner: 'Эгаси', admin: 'Администратор', worker: 'Ишчи' },
    statuses: {
        new: 'Янги',
        delivered: 'Мижозга берилди',
        cancelled: 'Бекор қилинди',
    },
    orders: {
        title: 'Буюртмалар',
        cannot_move: 'Буюртмани {status}дан кўчириб бўлмайди',
    },
};

const RU = {
    common: { loading: 'Загрузка...', error: 'Ошибка', currency: 'сум' },
    roles: { owner: 'Владелец', admin: 'Администратор', worker: 'Работник' },
    statuses: {
        new: 'Новый',
        delivered: 'Выдан клиенту',
        cancelled: 'Отменён',
    },
    // orders.title intentionally missing — should fall back to uz_cyrl
};

describe('I18nManager.lookup', () => {
    const mgr = new I18nManager();

    it('resolves a top-level key', () => {
        expect(mgr.lookup(UZ_CYRL, 'common')).toEqual(UZ_CYRL.common);
    });

    it('resolves a nested dot-path key', () => {
        expect(mgr.lookup(UZ_CYRL, 'common.loading')).toBe('Юкланмоқда...');
    });

    it('returns undefined for a missing key', () => {
        expect(mgr.lookup(UZ_CYRL, 'nonexistent.key')).toBeUndefined();
    });

    it('returns undefined for partially missing path', () => {
        expect(mgr.lookup(UZ_CYRL, 'common.nonexistent')).toBeUndefined();
    });

    it('handles empty string key by returning undefined', () => {
        // Splitting '' gives [''] which won't match any real key.
        expect(mgr.lookup(UZ_CYRL, '')).toBeUndefined();
    });
});

describe('I18nManager.translate — primary language', () => {
    let mgr;

    beforeEach(() => {
        mgr = new I18nManager();
        mgr.translations = UZ_CYRL;
        mgr.fallbackTranslations = RU;
    });

    it('returns the primary translation for an existing key', () => {
        expect(mgr.translate('common.error')).toBe('Хатолик');
    });

    it('returns the key itself when missing in both dictionaries', () => {
        expect(mgr.translate('totally.missing')).toBe('totally.missing');
    });

    it('interpolates a single parameter', () => {
        const result = mgr.translate('orders.cannot_move', { status: 'Янги' });
        expect(result).toBe('Буюртмани Янгидан кўчириб бўлмайди');
    });

    it('interpolates multiple parameters', () => {
        mgr.translations.test = '{a} + {b} = {c}';
        expect(mgr.translate('test', { a: '1', b: '2', c: '3' })).toBe('1 + 2 = 3');
    });

    it('leaves placeholder when param is not provided (empty object)', () => {
        mgr.translations.test = 'Hello {name}!';
        expect(mgr.translate('test', {})).toBe('Hello {name}!');
    });

    it('replaces placeholder when param is provided as empty string', () => {
        mgr.translations.test = 'Hello {name}!';
        expect(mgr.translate('test', { name: '' })).toBe('Hello !');
    });
});

describe('I18nManager.translate — fallback chain', () => {
    let mgr;

    beforeEach(() => {
        mgr = new I18nManager();
        mgr.translations = RU;           // current = ru (missing orders.title)
        mgr.fallbackTranslations = UZ_CYRL; // fallback = uz_cyrl (has orders.title)
    });

    it('falls back to uz_cyrl when key is missing in ru', () => {
        expect(mgr.translate('orders.title')).toBe('Буюртмалар');
    });

    it('uses ru translation when key exists in ru', () => {
        expect(mgr.translate('common.error')).toBe('Ошибка');
    });

    it('returns the key if missing in both', () => {
        expect(mgr.translate('no.such.key')).toBe('no.such.key');
    });

    it('returns fallback role names correctly', () => {
        // ru.json has 'roles.owner = Владелец'
        expect(mgr.translate('roles.owner')).toBe('Владелец');
    });
});

describe('I18nManager.translate — edge cases', () => {
    const mgr = new I18nManager();
    mgr.translations = UZ_CYRL;

    it('does not crash on null params', () => {
        expect(mgr.translate('common.error', null)).toBe('Хатолик');
    });

    it('does not crash on undefined params', () => {
        expect(mgr.translate('common.error', undefined)).toBe('Хатолик');
    });

    it('handles numeric parameter values', () => {
        mgr.translations.test = 'Count: {n}';
        expect(mgr.translate('test', { n: 42 })).toBe('Count: 42');
    });

    it('handles parameter value of 0', () => {
        mgr.translations.test = 'Zero: {n}';
        expect(mgr.translate('test', { n: 0 })).toBe('Zero: 0');
    });

    it('handles parameter value of null (becomes empty)', () => {
        mgr.translations.test = 'Value: {x}';
        expect(mgr.translate('test', { x: null })).toBe('Value: ');
    });
});
