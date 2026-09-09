/**
 * secureMedia unit tests.
 *
 * Unlike other frontend suites (which reimplement logic), this one loads the
 * REAL static/js/media.js into jsdom and drives window.secureMedia with a
 * mocked fetch — so regressions in the shipped file are caught here.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

function loadMediaJs() {
    const file = path.resolve(__dirname, '../../static/js/media.js');
    const code = fs.readFileSync(file, 'utf8');
    // eslint-disable-next-line no-eval
    (0, eval)(`${code}\n//# sourceURL=media.js`);
}

function mockFetchOnce(responses) {
    const queue = [...responses];
    const calls = [];
    globalThis.fetch = vi.fn(async (url, options = {}) => {
        calls.push({ url, options });
        const next = queue.shift() ?? queue[queue.length - 1];
        if (next instanceof Error) throw next;
        return {
            ok: next.status >= 200 && next.status < 300,
            status: next.status,
            blob: async () => new Blob(['bytes'], { type: 'image/jpeg' }),
        };
    });
    return calls;
}

describe('secureMedia (real static/js/media.js)', () => {
    beforeEach(() => {
        delete window.secureMedia;
        loadMediaJs();
        document.body.innerHTML = '';
        // jsdom has no blob-URL support — mock it.
        let counter = 0;
        globalThis.URL.createObjectURL = vi.fn(() => `blob:mock-${++counter}`);
        globalThis.URL.revokeObjectURL = vi.fn();
        window.api = {
            getTokens: () => ({ access: 'access-1', refresh: 'refresh-1' }),
            refreshToken: vi.fn(async () => null),
        };
    });

    afterEach(() => {
        window.secureMedia.reset();
        vi.restoreAllMocks();
    });

    it('detects same-origin /media/ paths and ignores the rest', () => {
        const pick = window.secureMedia._mediaPath;
        expect(pick('/media/avatars/a.jpg')).toBe('/media/avatars/a.jpg');
        expect(pick('media/avatars/a.jpg')).toBe('/media/avatars/a.jpg');
        expect(pick(`${location.origin}/media/x/y.png?v=2`)).toBe('/media/x/y.png');
        expect(pick('/static/js/app.js')).toBeNull();
        expect(pick('https://s3.example.com/media/a.jpg')).toBeNull();
        expect(pick('blob:mock-1')).toBeNull();
        expect(pick('data:image/png;base64,xx')).toBeNull();
        expect(pick('#/orders')).toBeNull();
        expect(pick('')).toBeNull();
        expect(pick(null)).toBeNull();
    });

    it('rewrites <img> src to an authorized blob URL', async () => {
        const calls = mockFetchOnce([{ status: 200 }]);
        document.body.innerHTML = '<img id="i" src="/media/materials/m.jpg">';
        window.secureMedia.scan(document);
        await vi.waitFor(() => {
            expect(document.getElementById('i').src).toContain('blob:mock-');
        });
        expect(calls).toHaveLength(1);
        expect(calls[0].options.headers).toEqual({
            Authorization: 'Bearer access-1',
        });
    });

    it('rewrites <a> href for media downloads, skips nav links', async () => {
        mockFetchOnce([{ status: 200 }]);
        document.body.innerHTML =
            '<a id="dl" href="/media/chat/attachments/f.pdf">file</a>' +
            '<a id="nav" href="#/orders">orders</a>';
        window.secureMedia.scan(document);
        await vi.waitFor(() => {
            expect(document.getElementById('dl').href).toContain('blob:mock-');
        });
        expect(document.getElementById('nav').getAttribute('href')).toBe('#/orders');
    });

    it('retries once with a refreshed token after 401', async () => {
        const calls = mockFetchOnce([{ status: 401 }, { status: 200 }]);
        window.api.refreshToken = vi.fn(async () => 'access-2');
        document.body.innerHTML = '<img id="i" src="/media/a.jpg">';
        window.secureMedia.scan(document);
        await vi.waitFor(() => {
            expect(document.getElementById('i').src).toContain('blob:mock-');
        });
        expect(calls).toHaveLength(2);
        expect(calls[1].options.headers).toEqual({
            Authorization: 'Bearer access-2',
        });
    });

    it('leaves the original src on 403 (component onerror fallback applies)', async () => {
        mockFetchOnce([{ status: 403 }]);
        document.body.innerHTML = '<img id="i" src="/media/a.jpg">';
        window.secureMedia.scan(document);
        await new Promise((r) => setTimeout(r, 20));
        const img = document.getElementById('i');
        expect(img.getAttribute('src')).toBe('/media/a.jpg');
        expect(img.dataset.mediaSecured).toBeUndefined();
    });

    it('deduplicates parallel requests for the same file', async () => {
        const calls = mockFetchOnce([{ status: 200 }]);
        document.body.innerHTML =
            '<img class="x" src="/media/logo.jpg">' +
            '<img class="x" src="/media/logo.jpg">';
        window.secureMedia.scan(document);
        await vi.waitFor(() => {
            const srcs = [...document.querySelectorAll('.x')].map((el) => el.src);
            expect(srcs[0]).toContain('blob:mock-');
            expect(srcs[1]).toBe(srcs[0]);
        });
        expect(calls).toHaveLength(1);
    });

    it('secures dynamically added nodes via MutationObserver', async () => {
        mockFetchOnce([{ status: 200 }]);
        window.secureMedia.init();
        const img = document.createElement('img');
        img.src = '/media/chat/new.jpg';
        document.body.appendChild(img);
        await vi.waitFor(() => {
            expect(img.src).toContain('blob:mock-');
        });
    });

    it('reset() revokes blob URLs and clears state', async () => {
        mockFetchOnce([{ status: 200 }]);
        document.body.innerHTML = '<img id="i" src="/media/a.jpg">';
        window.secureMedia.scan(document);
        await vi.waitFor(() => {
            expect(document.getElementById('i').src).toContain('blob:mock-');
        });
        window.secureMedia.reset();
        expect(globalThis.URL.revokeObjectURL).toHaveBeenCalled();
    });
});
