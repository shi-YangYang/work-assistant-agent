import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

export function browserEnvironment({ metadataPath, statePath }) {
  const paths = JSON.parse(
    execFileSync(
      resolve('.venv-server/bin/python'),
      [
        resolve('scripts/company/web-acceptance/runner_environment.py'),
        ...(metadataPath ? ['--metadata', metadataPath] : ['--state', statePath]),
      ],
      { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] },
    ),
  )
  return {
    metadata: JSON.parse(readFileSync(paths.metadataPath, 'utf8')),
    state: JSON.parse(readFileSync(paths.credentialsFile, 'utf8')),
  }
}

export async function api(page, path, method = 'GET', body) {
  if (!path.startsWith('/api/v1/')) throw new Error('Local API only')
  return page.evaluate(
    async ({ path, method, body }) => {
      const identity = await (await fetch('/api/v1/auth/me')).json()
      const response = await fetch(path, {
        method,
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': identity.csrf,
          ...(method === 'POST' ? { 'Idempotency-Key': crypto.randomUUID() } : {}),
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      })
      const data = await response.json()
      if (!response.ok)
        throw new Error(`HTTP ${response.status}: ${JSON.stringify(data).slice(0, 200)}`)
      return data
    },
    { path, method, body },
  )
}
