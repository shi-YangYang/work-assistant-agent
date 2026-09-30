import assert from 'node:assert/strict'
import test from 'node:test'
import { parseEnv } from 'node:util'
import { localConfig, patchLocalEnv } from '../../scripts/company/sandbox-local.mjs'

test('local setup preserves database/model credentials and replaces duplicate sandbox settings', () => {
  const original =
    '# Existing settings\nDATABASE_URL="postgres://user:secret@localhost/db"\nPAA_AGENT_API_KEY="existing#key"\nPAA_SANDBOX_URL=\nexport PAA_SANDBOX_URL=\nPAA_SANDBOX_TOKEN=\n'
  const config = localConfig(parseEnv(original))
  const updated = patchLocalEnv(original, config)
  const values = parseEnv(updated)
  assert.equal(values.DATABASE_URL, parseEnv(original).DATABASE_URL)
  assert.equal(values.PAA_AGENT_API_KEY, 'existing#key')
  assert.ok(updated.startsWith('# Existing settings\n'))
  assert.equal(updated.match(/PAA_SANDBOX_URL=/g).length, 1)
  assert.equal(values.PAA_SANDBOX_LOCAL, 'true')
  assert.equal(values.PAA_SANDBOX_URL, 'http://127.0.0.1:8011')
  assert.equal(values.PAA_SANDBOX_TOKEN.length, 64)
  assert.equal(patchLocalEnv(updated, localConfig(values)), updated)
})

test('setup refuses to overwrite a remote sandbox and rejects invalid local ports', () => {
  assert.throws(() => localConfig({ PAA_SANDBOX_URL: 'https://sandbox.example.com' }), /未被覆盖/)
  for (const port of ['0', '65536', 'abc', '12.5'])
    assert.throws(() => localConfig({ PAA_SANDBOX_LOCAL_PORT: port }), /端口/)
  assert.equal(localConfig({ PAA_SANDBOX_LOCAL_PORT: '8021' }).url, 'http://127.0.0.1:8021')
})
