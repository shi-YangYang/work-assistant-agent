import { defineConfig } from 'vitest/config'
import { resolve } from 'node:path'
export default defineConfig({
  esbuild: { jsx: 'automatic' },
  resolve: { alias: { '@web': resolve(import.meta.dirname, 'src') } },
  root: resolve(import.meta.dirname, '../..'),
  test: {
    include: ['tests/web/**/*.test.{ts,tsx}'],
    testTimeout: 10_000,
    setupFiles: ['tests/web/setup.ts'],
  },
})
