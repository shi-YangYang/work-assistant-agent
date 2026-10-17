import { createServer } from 'vite'
import { resolve } from 'node:path'
import { isolatedEnvironment } from '../../../../tests/e2e/web/fixtures/environment.mjs'
const state = isolatedEnvironment()
if (!process.env.SPEC073_OUTPUT || !process.env.SPEC073_ENVIRONMENT)
  throw new Error('Exact Spec073 environment and evidence directory required')
const server = await createServer({
  configFile: 'apps/web/vite.config.ts',
  cacheDir: resolve(process.env.SPEC073_OUTPUT, 'vite-cache'),
  server: {
    port: Number(new URL(state.origin).port),
    strictPort: true,
    proxy: { '^/api/v1(?:/|$)': { target: state.apiOrigin, changeOrigin: false } },
  },
})
await server.listen()
console.log(`Owned Spec073 Web ready at ${state.origin}`)
