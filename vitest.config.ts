import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: { include: ['tests/desktop/**/*.test.ts'], testTimeout: 10_000 },
})
