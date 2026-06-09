/**
 * Vitest config (EM-043) — frontend unit-test infrastructure.
 *
 * Deliberately standalone (NOT merged into vite.config.ts) so the production
 * build pipeline (`tsc -b && vite build`) is untouched. jsdom + globals so the
 * component smokes can render with @testing-library/react; the pure-logic
 * selector tests need neither but run in the same environment for simplicity.
 */
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.test.{ts,tsx}'],
    setupFiles: ['src/test-utils/setup.ts'],
  },
});
