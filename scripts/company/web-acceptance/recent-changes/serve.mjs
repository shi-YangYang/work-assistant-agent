import { createServer } from 'vite'
import { resolve } from 'node:path'
import { browserEnvironment } from '../../../../eval/web/agent-browser-common.mjs'
const { metadata, state } = browserEnvironment({ metadataPath: process.env.SPEC080_ENVIRONMENT })
if (metadata.suite !== 'spec080') throw new Error('Spec080 ownership required')
const server = await createServer({
  configFile: 'apps/web/vite.config.ts',
  cacheDir: resolve('artifacts/recent-changes-regression/private/vite-cache'),
  server: {
    port: Number(new URL(state.origin).port),
    strictPort: true,
    proxy: { '^/api/v1(?:/|$)': { target: state.apiOrigin, changeOrigin: false } },
  },
})
await server.listen()
console.log(`Owned Web ${state.origin}`)
