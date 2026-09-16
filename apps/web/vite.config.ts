import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { createRequire } from 'node:module'
import { cpSync, createReadStream, existsSync } from 'node:fs'
import { resolve } from 'node:path'
const pdfRoot = resolve(createRequire(import.meta.url).resolve('pdfjs-dist/package.json'), '..')
const pdfResources = ['cmaps', 'standard_fonts', 'wasm', 'iccs']
export default defineConfig({
  root: resolve(import.meta.dirname, 'src'),
  publicDir: resolve(import.meta.dirname, '../../packages/ui-web/public'),
  plugins: [
    react(),
    {
      name: 'local-pdf-resources',
      configureServer(server) {
        server.middlewares.use('/pdfjs', (request, response, next) => {
          const match = /^\/(cmaps|standard_fonts|wasm|iccs)\/([a-zA-Z0-9_.-]+)$/.exec(
            request.url ?? '',
          )
          if (!match) return next()
          const path = resolve(pdfRoot, match[1], match[2])
          if (!existsSync(path)) return next()
          response.setHeader(
            'Content-Type',
            match[2].endsWith('.wasm') ? 'application/wasm' : 'application/octet-stream',
          )
          createReadStream(path).pipe(response)
        })
      },
      closeBundle() {
        for (const directory of pdfResources)
          cpSync(
            resolve(pdfRoot, directory),
            resolve(import.meta.dirname, 'out/pdfjs', directory),
            { recursive: true },
          )
      },
    },
    {
      name: 'canonical-local-origin',
      apply: 'serve',
      configureServer(server) {
        server.middlewares.use((request, response, next) => {
          const address = server.httpServer?.address()
          if (
            !address ||
            typeof address === 'string' ||
            request.headers.host !== `localhost:${address.port}` ||
            !['GET', 'HEAD'].includes(request.method ?? '')
          ) {
            next()
            return
          }
          // Keep browser Origin aligned with the local API configuration.
          // Only redirect navigation/read requests; never rewrite a write's Origin.
          response.writeHead(307, {
            Location: `http://127.0.0.1:${address.port}${request.url ?? '/'}`,
            'Cache-Control': 'no-store',
          })
          response.end()
        })
      },
    },
  ],
  server: {
    host: '127.0.0.1',
    port: 5174,
    strictPort: true,
    proxy: { '^/api/': { target: 'http://127.0.0.1:8000', changeOrigin: false } },
  },
  build: { outDir: resolve(import.meta.dirname, 'out'), emptyOutDir: true },
})
