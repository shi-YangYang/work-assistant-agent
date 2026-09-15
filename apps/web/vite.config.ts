import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'
export default defineConfig({
  root: resolve(import.meta.dirname, 'src'),
  publicDir: resolve(import.meta.dirname, '../../packages/ui-web/public'),
  plugins: [
    react(),
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
