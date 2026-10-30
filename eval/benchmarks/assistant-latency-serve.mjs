import { createServer } from 'vite'
import { resolve } from 'node:path'
import { browserEnvironment } from '../web/agent-browser-common.mjs'

const { metadata, state } = browserEnvironment({ metadataPath: process.argv[2] })
if (metadata.suite !== 'spec081') throw new Error('Owned Spec081 environment required')
const server = await createServer({
  configFile: 'apps/web/vite.config.ts',
  cacheDir: resolve('artifacts/agent-response-latency', metadata.runId, 'vite-cache'),
  server: {
    port: Number(new URL(state.origin).port),
    strictPort: true,
    proxy: { '^/api/v1(?:/|$)': { target: state.apiOrigin, changeOrigin: false } },
  },
})
await server.listen()
console.log(`Owned Web ${state.origin}`)
