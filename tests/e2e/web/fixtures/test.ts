import { test as base, expect, type Page } from '@playwright/test'
import { readFileSync, statSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

type Account = { id: string; companyId: string; username: string; password: string; role: string }
type State = {
  origin: string
  apiOrigin: string
  runId: string
  schema: string
  users: Record<string, Account>
}

export function environment(): State {
  const path = process.env.SPEC044_STATE
  if (!path) throw new Error('SPEC044_STATE must identify isolated acceptance credentials')
  if (statSync(path).mode & 0o077) throw new Error('Credentials must have mode 0600')
  const state = JSON.parse(readFileSync(path, 'utf8')) as State
  if (!/^spec044_web_[a-f0-9]{12}$/.test(state.schema)) throw new Error('Not a Spec044 schema')
  const url = new URL(state.origin)
  if (url.hostname !== '127.0.0.1' || url.port !== '5196') throw new Error('Not the test UI')
  return state
}

type Fixtures = {
  state: State
  login: (role?: string) => Promise<void>
  capture: (name: string) => Promise<void>
  http: <T = unknown>(
    path: string,
    method?: string,
    body?: unknown,
  ) => Promise<{ status: number; data: T }>
}

export async function login(page: Page, state: State, role = 'admin') {
  await page.goto(state.origin)
  await page.getByRole('button', { name: /直接登录/ }).click()
  await page.getByLabel('账号', { exact: true }).fill(state.users[role].username)
  await page.getByLabel('密码', { exact: true }).fill(state.users[role].password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('navigation', { name: '工作空间' })).toBeAttached()
}

export const test = base.extend<Fixtures>({
  state: async ({ browserName }, use) => {
    void browserName
    await use(environment())
  },
  login: async ({ page, state }, use) => {
    await use((role) => login(page, state, role))
  },
  http: async ({ page }, use) => {
    await use(async (path, method = 'GET', body) => {
      if (!path.startsWith('/api/v1/')) throw new Error('Only local business API paths are allowed')
      return page.evaluate(
        async ({ path, method, body }) => {
          const identity = await (await fetch('/api/v1/auth/me')).json()
          const response = await fetch(path, {
            method,
            headers: {
              'Content-Type': 'application/json',
              'X-CSRF-Token': identity.csrf,
              'Idempotency-Key': crypto.randomUUID(),
            },
            ...(body === undefined ? {} : { body: JSON.stringify(body) }),
          })
          return { status: response.status, data: await response.json() }
        },
        { path, method, body },
      )
    })
  },
  capture: async ({ page }, use, info) => {
    const errors: string[] = []
    const requests: { method: string; path: string; status: number }[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    page.on('response', (response) => {
      const path = new URL(response.url()).pathname
      if (path.startsWith('/api/v1/'))
        requests.push({ method: response.request().method(), path, status: response.status() })
    })
    await use(async (name) => {
      await page.screenshot({ path: info.outputPath(`${name}.png`) })
      const size = await page.evaluate(() => ({
        viewport: innerWidth,
        document: document.documentElement.scrollWidth,
      }))
      expect(size.document, `${name} horizontal overflow`).toBeLessThanOrEqual(size.viewport + 1)
    })
    writeFileSync(
      info.outputPath('evidence.json'),
      JSON.stringify({ title: info.title, errors, requests }, null, 2),
    )
    expect(errors, 'uncaught browser errors').toEqual([])
  },
})

export { expect, resolve }
