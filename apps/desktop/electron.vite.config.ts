import { resolve } from 'node:path'
import { defineConfig, loadEnv } from 'electron-vite'
import react from '@vitejs/plugin-react'
import { companyOrigin } from './src/main/company-connection'

export function defaultCompanyUrl(
  mode: string,
  envDir = resolve(import.meta.dirname, '../..'),
): string {
  const value =
    loadEnv(mode, envDir, 'PAA_DESKTOP_COMPANY_URL').PAA_DESKTOP_COMPANY_URL?.trim() ?? ''
  if (!value) return ''
  try {
    if (value.length > 2048) throw new Error('length')
    return companyOrigin(value)
  } catch {
    throw new Error('PAA_DESKTOP_COMPANY_URL 须为公司 HTTPS 根地址；本机开发可使用 HTTP 回环地址。')
  }
}

export default defineConfig(({ mode }) => ({
  main: {
    define: { __PAA_DESKTOP_COMPANY_URL__: JSON.stringify(defaultCompanyUrl(mode)) },
    build: {
      externalizeDeps: { exclude: ['@paa/model-config', '@paa/ui-web'] },
      rollupOptions: { input: { index: resolve(import.meta.dirname, 'src/main/main.ts') } },
    },
  },
  preload: {
    build: {
      rollupOptions: { input: { index: resolve(import.meta.dirname, 'src/preload/index.ts') } },
    },
  },
  renderer: {
    root: resolve(import.meta.dirname, 'src/renderer'),
    publicDir: resolve(import.meta.dirname, '../../packages/ui-web/brand/web'),
    plugins: [
      react(),
      {
        name: 'local-content-policy',
        transformIndexHtml(html, context) {
          const policy = context.server
            ? "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self' ws://127.0.0.1:5173; img-src 'self' data:; media-src paa-audio:; object-src 'none'; base-uri 'none'; form-action 'none'"
            : "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'none'; img-src 'self' data:; media-src paa-audio:; object-src 'none'; base-uri 'none'; form-action 'none'"
          return html.replace('__CONTENT_POLICY__', policy)
        },
      },
    ],
    server: { host: '127.0.0.1', port: 5173, strictPort: true },
    build: { rollupOptions: { input: resolve(import.meta.dirname, 'src/renderer/index.html') } },
  },
}))
