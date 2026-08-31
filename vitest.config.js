import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: true,
    environment: 'jsdom',
    include: ['tests/frontend/**/*.test.js'],
    setupFiles: ['tests/frontend/setup.js'],
  },
  resolve: {
    alias: {
      // Map project static JS so tests can import them
      '@static': '/static/js',
    },
  },
});
