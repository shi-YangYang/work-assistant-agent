import { createServer as createHttpServer, request } from 'node:http'
import type { AddressInfo } from 'node:net'
import { resolve } from 'node:path'
import { createServer, type ViteDevServer } from 'vite'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import webConfig from '../../apps/web/vite.config'

describe('local Web origin', () => {
  let web: ViteDevServer
  let port: number
  const api = createHttpServer((req, res) => {
    res.setHeader('Content-Type', 'application/json')
    res.end(JSON.stringify({ origin: req.headers.origin, method: req.method }))
  })

  beforeAll(async () => {
    await new Promise<void>((done) => api.listen(0, '127.0.0.1', done))
    const apiPort = (api.address() as AddressInfo).port
    web = await createServer({
      configFile: resolve('apps/web/vite.config.ts'),
      logLevel: 'silent',
      server: {
        port: 0,
        hmr: false,
        watch: null,
        proxy: Object.fromEntries(
          Object.keys(webConfig.server!.proxy!).map((prefix) => [
            prefix,
            { target: `http://127.0.0.1:${apiPort}`, changeOrigin: false },
          ]),
        ),
      },
      optimizeDeps: { noDiscovery: true, include: [] },
    })
    await web.listen()
    port = (web.httpServer!.address() as AddressInfo).port
  })

  afterAll(async () => {
    await web?.close()
    await new Promise<void>((done, reject) =>
      api.close((error) => (error ? reject(error) : done())),
    )
  })

  function get(path: string, hostname = 'localhost', method = 'GET', origin?: string) {
    return new Promise<{ status: number; location?: string; cache?: string; body: string }>(
      (done, reject) => {
        const req = request(
          {
            hostname: '127.0.0.1',
            port,
            path,
            method,
            headers: { Host: `${hostname}:${port}`, ...(origin ? { Origin: origin } : {}) },
          },
          (res) => {
            let body = ''
            res.setEncoding('utf8')
            res.on('data', (chunk) => (body += chunk))
            res.on('end', () =>
              done({
                status: res.statusCode!,
                location: res.headers.location,
                cache: res.headers['cache-control'],
                body,
              }),
            )
          },
        )
        req.on('error', reject)
        req.end()
      },
    )
  }

  it.each(['GET', 'HEAD'])(
    'redirects %s navigation while preserving the route and query',
    async (method) => {
      expect(await get('/assistant?conversation=example', 'localhost', method)).toMatchObject({
        status: 307,
        location: `http://127.0.0.1:${port}/assistant?conversation=example`,
        cache: 'no-store',
      })
    },
  )

  it('serves the canonical address without a redirect loop', async () => {
    const response = await get('/', '127.0.0.1')
    expect(response.status).toBe(200)
    expect(response.location).toBeUndefined()
    expect(response.body).toContain('工作助手')
  })

  it('keeps protocol-relative paths on the canonical host', async () => {
    const response = await get('//other.invalid/assistant')
    expect(response.status).toBe(307)
    expect(new URL(response.location!).origin).toBe(`http://127.0.0.1:${port}`)
  })

  it('serves the frontend API modules through Vite instead of proxying them to Python', async () => {
    const response = await get('/api/client.ts', '127.0.0.1')
    expect(response.status).toBe(200)
    expect(response.body).toContain('cancelledRequest')
    expect(response.body).toContain('/api/v1')
  })

  it('does not redirect writes or replace an untrusted Origin in the API proxy', async () => {
    const response = await get('/api/v1/auth/login', 'localhost', 'POST', 'https://other.invalid')
    expect(response.status).toBe(200)
    expect(response.location).toBeUndefined()
    expect(JSON.parse(response.body)).toEqual({ origin: 'https://other.invalid', method: 'POST' })
  })
})
