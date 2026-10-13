import { execFileSync } from 'node:child_process'
import { readFileSync, statSync } from 'node:fs'
import { dirname, resolve } from 'node:path'

// Every browser mutation must first verify the disposable schema's ownership marker.
export function isolatedEnvironment() {
  const manifestPath = process.env.SPEC068_ENVIRONMENT
    ? resolve(process.env.SPEC068_ENVIRONMENT)
    : process.env.SPEC054_ENVIRONMENT
      ? resolve(process.env.SPEC054_ENVIRONMENT)
      : process.env.SPEC044_STATE
        ? resolve(dirname(process.env.SPEC044_STATE), 'environment.json')
        : null
  if (!manifestPath)
    throw new Error('SPEC068_ENVIRONMENT, SPEC054_ENVIRONMENT or SPEC044_STATE is required')
  const metadata = JSON.parse(readFileSync(manifestPath, 'utf8'))
  if (
    !['spec044', 'spec054', 'spec055', 'spec056', 'spec068'].includes(metadata.suite ?? 'spec044')
  )
    throw new Error('Unrecognized acceptance suite')
  if (metadata.purpose !== 'web') throw new Error('Not a browser acceptance environment')
  const suite = metadata.suite ?? 'spec044'
  if (
    !/^[a-f0-9]{32}$/.test(metadata.runId) ||
    metadata.schema !== `${suite}_web_${metadata.runId.slice(0, 12)}`
  )
    throw new Error('Invalid disposable schema identity')
  execFileSync(
    resolve('.venv-server/bin/python'),
    [
      '-c',
      [
        'import sys',
        "sys.path.insert(0, 'scripts/company/web-acceptance')",
        'from environment import load_environment',
        'load_environment(sys.argv[1])',
      ].join('\n'),
      manifestPath,
    ],
    { stdio: 'pipe' },
  )
  const credentialsPath = resolve(metadata.credentialsFile)
  if (credentialsPath !== resolve(dirname(manifestPath), 'credentials.json'))
    throw new Error('Unexpected credentials location')
  if (process.env.SPEC044_STATE && resolve(process.env.SPEC044_STATE) !== credentialsPath)
    throw new Error('Credentials do not belong to this manifest')
  if (statSync(credentialsPath).mode & 0o077) throw new Error('Credentials must have mode 0600')
  const state = JSON.parse(readFileSync(credentialsPath, 'utf8'))
  if (
    state.schema !== metadata.schema ||
    state.runId !== metadata.runId ||
    state.origin !== metadata.origin ||
    state.apiOrigin !== metadata.apiOrigin
  )
    throw new Error('Credentials and manifest identity differ')
  const ports =
    suite === 'spec056' ? [5206, 8036] : suite === 'spec055' ? [5198, 8020] : [5196, 8016]
  if (
    state.origin !== `http://127.0.0.1:${ports[0]}` ||
    state.apiOrigin !== `http://127.0.0.1:${ports[1]}`
  )
    throw new Error('Only the dedicated browser API and UI are allowed')
  for (const role of ['admin', 'employee']) {
    if (
      !state.users[role]?.password ||
      state.users[role].id !== metadata.accounts[role].id ||
      state.users[role].companyId !== metadata.accounts[role].companyId
    )
      throw new Error('Account does not belong to this manifest')
  }
  return state
}
