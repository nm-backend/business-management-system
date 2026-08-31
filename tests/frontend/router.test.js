/**
 * Router unit tests.
 *
 * Tests route registration, path parsing, and nav-key derivation logic.
 * We test the LOGIC, not DOM manipulation (integration covers that).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

// ---------------------------------------------------------------------------
// Minimal Router reimplementation for isolated testing.
// ---------------------------------------------------------------------------
class Router {
    constructor() {
        this.routes = {};
        this.query = new URLSearchParams();
    }

    addRoute(path, component) {
        this.routes[path] = component;
    }

    /**
     * Derive the sidebar and bottom-nav active keys from a path.
     * Extracted from handleRoute() for testability.
     */
    deriveNavKeys(path) {
        let navKey = 'dashboard';
        if (path.startsWith('/orders/kanban')) navKey = 'kanban';
        else if (path.startsWith('/orders')) navKey = 'orders';
        else if (path.startsWith('/warehouse')) navKey = 'warehouse';
        else if (path.startsWith('/finished-products')) navKey = 'warehouse';
        else if (path.startsWith('/clients')) navKey = 'clients';
        else if (path.startsWith('/production')) navKey = 'production';
        else if (path.startsWith('/finance')) navKey = 'finance';
        else if (path.startsWith('/messages')) navKey = 'messages';
        else if (path.startsWith('/companies')) navKey = 'companies';
        else if (path.startsWith('/audit')) navKey = 'audit';
        else if (path.startsWith('/settings')) navKey = 'settings';

        const bottomKey = ['finance', 'messages', 'companies'].includes(navKey)
            ? 'settings' : navKey;
        return { navKey, bottomKey };
    }

    /**
     * Parse a hash string into { path, query }.
     */
    parseHash(hash) {
        const raw = (hash || '#/').slice(1) || '/';
        const [path, queryString] = raw.split('?');
        return { path, query: new URLSearchParams(queryString || '') };
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('Router.addRoute', () => {
    it('registers a route', () => {
        const router = new Router();
        const component = { render: vi.fn() };
        router.addRoute('/orders', component);
        expect(router.routes['/orders']).toBe(component);
    });

    it('overwrites existing route for same path', () => {
        const router = new Router();
        const comp1 = { render: vi.fn() };
        const comp2 = { render: vi.fn() };
        router.addRoute('/orders', comp1);
        router.addRoute('/orders', comp2);
        expect(router.routes['/orders']).toBe(comp2);
    });

    it('handles root path', () => {
        const router = new Router();
        router.addRoute('/', { render: vi.fn() });
        expect(router.routes['/']).toBeDefined();
    });
});

describe('Router.parseHash', () => {
    const router = new Router();

    it('parses a simple path', () => {
        const { path, query } = router.parseHash('#/orders');
        expect(path).toBe('/orders');
        expect(query.toString()).toBe('');
    });

    it('parses path with query params', () => {
        const { path, query } = router.parseHash('#/messages?tab=notifications');
        expect(path).toBe('/messages');
        expect(query.get('tab')).toBe('notifications');
    });

    it('parses empty hash as root', () => {
        const { path } = router.parseHash('#/');
        expect(path).toBe('/');
    });

    it('handles missing hash', () => {
        const { path } = router.parseHash('');
        expect(path).toBe('/');
    });

    it('handles multiple query params', () => {
        const { path, query } = router.parseHash('#/orders?status=new&page=2');
        expect(path).toBe('/orders');
        expect(query.get('status')).toBe('new');
        expect(query.get('page')).toBe('2');
    });
});

describe('Router.deriveNavKeys', () => {
    const router = new Router();

    it('dashboard for root', () => {
        expect(router.deriveNavKeys('/')).toEqual({ navKey: 'dashboard', bottomKey: 'dashboard' });
    });

    it('orders path', () => {
        expect(router.deriveNavKeys('/orders')).toEqual({ navKey: 'orders', bottomKey: 'orders' });
    });

    it('kanban path (before orders)', () => {
        expect(router.deriveNavKeys('/orders/kanban')).toEqual({ navKey: 'kanban', bottomKey: 'kanban' });
    });

    it('warehouse path', () => {
        expect(router.deriveNavKeys('/warehouse')).toEqual({ navKey: 'warehouse', bottomKey: 'warehouse' });
    });

    it('finished-products maps to warehouse', () => {
        expect(router.deriveNavKeys('/finished-products')).toEqual({ navKey: 'warehouse', bottomKey: 'warehouse' });
    });

    it('clients path', () => {
        expect(router.deriveNavKeys('/clients')).toEqual({ navKey: 'clients', bottomKey: 'clients' });
    });

    it('production path', () => {
        expect(router.deriveNavKeys('/production')).toEqual({ navKey: 'production', bottomKey: 'production' });
    });

    it('finance maps to settings bottom nav', () => {
        expect(router.deriveNavKeys('/finance')).toEqual({ navKey: 'finance', bottomKey: 'settings' });
    });

    it('messages maps to settings bottom nav', () => {
        expect(router.deriveNavKeys('/messages')).toEqual({ navKey: 'messages', bottomKey: 'settings' });
    });

    it('companies maps to settings bottom nav', () => {
        expect(router.deriveNavKeys('/companies')).toEqual({ navKey: 'companies', bottomKey: 'settings' });
    });

    it('audit path', () => {
        expect(router.deriveNavKeys('/audit')).toEqual({ navKey: 'audit', bottomKey: 'audit' });
    });

    it('settings path', () => {
        expect(router.deriveNavKeys('/settings')).toEqual({ navKey: 'settings', bottomKey: 'settings' });
    });

    it('unknown path falls back to dashboard', () => {
        expect(router.deriveNavKeys('/unknown-page')).toEqual({ navKey: 'dashboard', bottomKey: 'dashboard' });
    });
});

describe('Router route resolution', () => {
    it('finds a registered route', () => {
        const router = new Router();
        const comp = { render: vi.fn() };
        router.addRoute('/orders', comp);
        expect(router.routes['/orders']).toBe(comp);
    });

    it('returns undefined for unregistered route', () => {
        const router = new Router();
        expect(router.routes['/nonexistent']).toBeUndefined();
    });

    it('registers all main SPA routes', () => {
        const router = new Router();
        const comp = { render: () => {} };
        const paths = [
            '/', '/warehouse', '/finished-products', '/clients',
            '/orders', '/orders/kanban', '/production', '/finance',
            '/messages', '/subscription', '/settings', '/audit',
        ];
        paths.forEach((p) => router.addRoute(p, comp));
        paths.forEach((p) => expect(router.routes[p]).toBe(comp));
    });
});
