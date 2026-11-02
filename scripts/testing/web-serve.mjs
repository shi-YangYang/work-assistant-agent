import { createServer } from 'vite'
import { resolve } from 'node:path'
import { isolatedEnvironment } from '../../tests/e2e/web/fixtures/environment.mjs'
const state = isolatedEnvironment()
const server = await createServer({
  configFile: 'apps/web/vite.config.ts',
  cacheDir: resolve(process.env.PROJECT_TEST_OUTPUT, 'vite-cache'),
  server: {
    host: '127.0.0.1',
    port: Number(new URL(state.origin).port),
    strictPort: true,
    proxy: { '^/api/v1(?:/|$)': { target: state.apiOrigin, changeOrigin: false } },
  },
})
await server.listen()
