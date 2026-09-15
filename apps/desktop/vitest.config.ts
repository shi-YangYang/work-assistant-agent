import { defineConfig } from 'vitest/config'
import { resolve } from 'node:path'
export default defineConfig({
  root: resolve(import.meta.dirname, '../..'),
  test: { include: ['tests/desktop/**/*.test.ts'], testTimeout: 10_000 },
})
