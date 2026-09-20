import { defineConfig } from 'vitest/config'
import { resolve } from 'node:path'
export default defineConfig({
  resolve: { alias: { '@web': resolve(import.meta.dirname, 'src') } },
  root: resolve(import.meta.dirname, '../..'),
  test: { include: ['tests/web/**/*.test.ts'], testTimeout: 10_000 },
})
