import { resolve } from 'node:path'
import { defineConfig } from 'electron-vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  main: {
    build: { rollupOptions: { input: { index: resolve('src/desktop/main.ts') } } },
  },
  preload: {
    build: { rollupOptions: { input: { index: resolve('src/desktop/preload.ts') } } },
  },
  renderer: {
    root: resolve('src/renderer'),
    plugins: [
      react(),
      {
        name: 'local-content-policy',
        transformIndexHtml(html, context) {
          const policy = context.server
            ? "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self' ws://127.0.0.1:5173; img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'none'"
            : "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'none'; img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'none'"
          return html.replace('__CONTENT_POLICY__', policy)
        },
      },
    ],
    server: { host: '127.0.0.1', port: 5173, strictPort: true },
    build: { rollupOptions: { input: resolve('src/renderer/index.html') } },
  },
})
