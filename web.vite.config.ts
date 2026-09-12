import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'
export default defineConfig({
  root: resolve('src/web'),
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5174,
    strictPort: true,
    proxy: { '^/api/': { target: 'http://127.0.0.1:8000', changeOrigin: false } },
  },
  build: { outDir: resolve('out/web'), emptyOutDir: true },
})
