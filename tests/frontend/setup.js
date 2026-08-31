/**
 * Vitest global setup: polyfill browser APIs that static/js modules expect.
 */
import { vi } from 'vitest';

// localStorage mock
const store = {};
globalThis.localStorage = {
  getItem: (key) => store[key] ?? null,
  setItem: (key, val) => { store[key] = String(val); },
  removeItem: (key) => { delete store[key]; },
  clear: () => { Object.keys(store).forEach((k) => delete store[k]); },
};

// window.i18n stub — tests override per-file
globalThis.window = globalThis.window || {};
globalThis.window.i18n = { translate: (key) => key, applyTranslations: () => {} };
globalThis.window.ui = globalThis.window.ui || {};
globalThis.window.toast = { error: () => {}, success: () => {}, info: () => {} };

// document.location for router tests
if (!globalThis.location.hash) globalThis.location.hash = '#/';
