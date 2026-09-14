import { defineConfig } from 'vitest/config'
export default defineConfig({ test: { include: ['tests/web/**/*.test.ts'], testTimeout: 10000 } })
