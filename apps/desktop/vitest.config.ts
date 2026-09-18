import { defineConfig } from 'vitest/config'
import { resolve } from 'node:path'
export default defineConfig({
  root: resolve(import.meta.dirname, '../..'),
  // Match the build-time constant without loading a developer's company configuration.
  define: { __PAA_DESKTOP_COMPANY_URL__: JSON.stringify('') },
  test: { include: ['tests/desktop/**/*.test.ts'], testTimeout: 10_000 },
})
