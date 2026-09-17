import { afterEach, describe, expect, it, vi } from 'vitest'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { createHash } from 'node:crypto'
import {
  CompanyConnection,
  VOICEPRINT_MODEL,
  companyOrigin,
  voiceprintSnapshot,
  type VoiceprintConfiguration,
} from '../../apps/desktop/src/main/company-connection'
import { validCompanyRequest } from '../../apps/desktop/src/shared/company-contracts'
import type { VoiceprintStatus } from '../../apps/desktop/src/shared/company-contracts'
const roots: string[] = [],
  connections: CompanyConnection[] = []
const secrets = {
  isAsyncEncryptionAvailable: async () => true,
  encryptStringAsync: async (value: string) => Buffer.from([...value].reverse().join('')),
  decryptStringAsync: async (value: Buffer) => ({
    result: [...value.toString()].reverse().join(''),
  }),
}
const account = {
  member: { id: 'admin-id', name: '管理员', role: 'admin' },
  company: { id: 'company-id', name: '公司甲' },
}
const requestId = 'r'.repeat(43),
  token = 'private-company-access-token'
const vector = Array.from({ length: 256 }, (_, index) => (index === 0 ? 1 : 0))
const snapshot = {
  modelId: VOICEPRINT_MODEL,
  revision: 'revision-1',
  profiles: [{ memberId: 'employee-id', name: '员工甲', templates: [vector] }],
}
const expires = () => new Date(Date.now() + 60_000).toISOString()
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
afterEach(async () => {
  connections.splice(0).forEach((c) => c.dispose())
  vi.useRealTimers()
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })))
})
async function fixture(configuredServerUrl = 'https://company.example') {
  const root = await mkdtemp(join(tmpdir(), 'paa-company-'))
  roots.push(root)
  let challenge = ''
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const path = new URL(String(input)).pathname
    const body = init?.body ? JSON.parse(String(init.body)) : {}
    expect(init?.redirect).toBe('error')
    if (path.endsWith('/info'))
      return json({ protocolVersion: 1, webOrigin: 'https://company.example' })
    if (path.endsWith('/login/start')) {
      challenge = body.challenge
      return json({
        requestId,
        expiresAt: expires(),
        authorizationUrl: `https://company.example/desktop/connect?request=${requestId}`,
      })
    }
    if (path.endsWith('/login/exchange')) {
      expect(body.requestId).toBe(requestId)
      expect(createHash('sha256').update(body.verifier).digest('base64url')).toBe(challenge)
      return json({ ...account, token, expiresAt: expires() })
    }
    expect(init?.headers).toMatchObject({ Authorization: `Bearer ${token}` })
    if (path.endsWith('/me')) return json({ ...account, expiresAt: expires() })
    if (path.endsWith('/voiceprints')) return json(snapshot)
    return json({ ok: true })
  })
  const core = vi.fn(
    async (
      _action: 'configure' | 'status',
      config?: VoiceprintConfiguration,
    ): Promise<VoiceprintStatus> => ({
      enabled: !!config?.profiles.length,
      profileCount: config?.profiles.length ?? 0,
      modelId: VOICEPRINT_MODEL,
      state: config?.profiles.length ? 'ready' : 'disabled',
      error: null,
    }),
  )
  const browser = vi.fn(async () => undefined)
  const create = (serverUrl = configuredServerUrl) => {
    const c = new CompanyConnection(root, secrets, core, browser, undefined, fetcher, serverUrl)
    connections.push(c)
    return c
  }
  const connection = create()
  await connection.load()
  return { root, connection, create, fetcher, core, browser }
}
async function login(connection: CompanyConnection) {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] })
  const result = await connection.execute({ action: 'login' })
  expect(result.session).toBe('authorizing')
  await vi.advanceTimersByTimeAsync(2000)
  await vi.waitFor(() => expect(connection.status().session).toBe('signed-in'))
}
describe('company connection trust and IPC boundary', () => {
  it('uses the configured address without creating a session or contacting the server', async () => {
    const { root, connection, fetcher, browser } = await fixture('https://bundled.example/')
    expect(connection.status()).toMatchObject({
      serverUrl: 'https://bundled.example',
      session: 'guest',
      identity: null,
      profileCount: 0,
    })
    expect(fetcher).not.toHaveBeenCalled()
    expect(browser).not.toHaveBeenCalled()
    await expect(readFile(join(root, 'company-connection.enc'))).rejects.toMatchObject({
      code: 'ENOENT',
    })
    expect((await fixture('')).connection.status().serverUrl).toBe('')
  })
  it.each(['', 'https://other.example'])(
    'does not restore another company or contact it when the configured address is %s',
    async (serverUrl) => {
      const { root, connection, create, fetcher, core, browser } = await fixture()
      await login(connection)
      await connection.execute({ action: 'sync' })
      const cached = await readFile(join(root, 'company-connection.enc'))
      connection.dispose()
      fetcher.mockClear()
      browser.mockClear()
      const restarted = create(serverUrl)
      await restarted.load()
      await restarted.apply()
      expect(restarted.status()).toMatchObject({
        serverUrl,
        session: 'guest',
        identity: null,
        profileCount: 0,
        error: null,
      })
      expect(core).toHaveBeenLastCalledWith('configure', {
        scope: null,
        modelId: VOICEPRINT_MODEL,
        profiles: [],
      })
      if (!serverUrl) {
        for (const action of ['login', 'sync', 'clear', 'logout'] as const) {
          expect(await restarted.execute({ action })).toMatchObject({
            session: 'guest',
            identity: null,
            profileCount: 0,
            error: '尚未配置公司服务地址，请联系管理员配置后再登录。',
          })
        }
      }
      expect(fetcher).not.toHaveBeenCalled()
      expect(browser).not.toHaveBeenCalled()
      expect(await readFile(join(root, 'company-connection.enc'))).toEqual(cached)
      const restored = create()
      await restored.load()
      expect(restored.status()).toMatchObject({
        serverUrl: 'https://company.example',
        session: 'signed-in',
        identity: account,
        profileCount: 1,
      })
    },
  )
  it.each(['info', 'login/exchange'])(
    'can retry login in the same instance after the network recovers from a failed %s request',
    async (stage) => {
      const { connection, fetcher, browser } = await fixture()
      const original = fetcher.getMockImplementation()!
      let offline = true
      fetcher.mockImplementation((input, init) => {
        if (offline && String(input).endsWith(`/${stage}`)) {
          offline = false
          return Promise.reject(new Error('network offline'))
        }
        return original(input, init)
      })
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] })
      await connection.execute({ action: 'login' })
      if (stage === 'login/exchange') await vi.advanceTimersByTimeAsync(2000)
      expect(connection.status()).toMatchObject({
        session: 'guest',
        busy: false,
        identity: null,
        error: expect.stringContaining('无法连接'),
      })
      await login(connection)
      const result = await connection.execute({ action: 'sync' })
      expect(result).toMatchObject({
        session: 'signed-in',
        busy: false,
        error: null,
        profileCount: 1,
      })
      expect(browser).toHaveBeenCalledTimes(stage === 'info' ? 1 : 2)
    },
  )
  it('only accepts bounded commands and HTTPS origins or literal loopback development URLs', () => {
    expect(companyOrigin('https://company.example/api/v1/')).toBe('https://company.example')
    expect(companyOrigin('http://127.0.0.1:5174')).toBe('http://127.0.0.1:5174')
    for (const input of [
      'http://company.example',
      'https://a:b@company.example',
      'file:///secret',
      'https://company.example/?token=secret',
      'https://company.example/path',
    ])
      expect(() => companyOrigin(input)).toThrow()
    expect(validCompanyRequest({ action: 'login' })).toBe(true)
    for (const value of [
      { action: 'sync', token: 'steal' },
      { action: 'configure', profiles: [] },
      { action: 'login', serverUrl: 'https://attacker.example' },
      { action: 'login', serverUrl: 1 },
      ['logout'],
    ])
      expect(validCompanyRequest(value)).toBe(false)
  })
  it('does not open service-supplied external origins or send credentials through redirects', async () => {
    const { connection, fetcher, browser } = await fixture()
    fetcher.mockResolvedValueOnce(
      json({ protocolVersion: 1, webOrigin: 'https://attacker.example' }),
    )
    const mismatch = await connection.execute({
      action: 'login',
    })
    expect(mismatch.error).toContain('不一致')
    expect(browser).not.toHaveBeenCalled()
    fetcher.mockResolvedValueOnce(
      new Response('', { status: 302, headers: { location: 'https://attacker.example' } }),
    )
    expect((await connection.execute({ action: 'login' })).error).toContain('重定向')
    expect(browser).not.toHaveBeenCalled()
  })
  it('rejects a forged browser authorization URL even after valid discovery', async () => {
    const { connection, fetcher, browser } = await fixture()
    fetcher.mockResolvedValueOnce(
      json({ protocolVersion: 1, webOrigin: 'https://company.example' }),
    )
    fetcher.mockResolvedValueOnce(
      json({
        requestId,
        expiresAt: expires(),
        authorizationUrl: `https://company.example/desktop/connect?request=${requestId}&token=extra`,
      }),
    )
    expect((await connection.execute({ action: 'login' })).error).toContain('登录网页无效')
    expect(browser).not.toHaveBeenCalled()
  })
  it('rejects incompatible, duplicate and malformed templates', () => {
    expect(() => voiceprintSnapshot({ ...snapshot, modelId: 'other-version' })).toThrow('不兼容')
    expect(() =>
      voiceprintSnapshot({ ...snapshot, profiles: [...snapshot.profiles, ...snapshot.profiles] }),
    ).toThrow('模板无效')
    expect(() =>
      voiceprintSnapshot({
        ...snapshot,
        profiles: [{ ...snapshot.profiles[0], templates: [[1]] }],
      }),
    ).toThrow('特征无效')
    expect(() =>
      voiceprintSnapshot({
        ...snapshot,
        profiles: [{ ...snapshot.profiles[0], templates: [vector.map(() => 0)] }],
      }),
    ).toThrow('特征无效')
    expect(() => voiceprintSnapshot({ ...snapshot, revision: undefined })).toThrow()
  })
})
describe('durable offline company voiceprints', () => {
  it('completes PKCE, encrypts credentials/templates and restores the same scoped cache without network', async () => {
    const { root, connection, create, fetcher, core, browser } = await fixture()
    await login(connection)
    expect(browser).toHaveBeenCalledWith(
      `https://company.example/desktop/connect?request=${requestId}`,
    )
    const status = await connection.execute({ action: 'sync' })
    expect(status.profileCount).toBe(1)
    expect(status.engine?.enabled).toBe(true)
    expect(JSON.stringify(status)).not.toMatch(/templates|private-company-access-token|employee-id/)
    const disk = await readFile(join(root, 'company-connection.enc'), 'utf8')
    expect(disk).not.toContain(token)
    expect(disk).not.toContain('employee-id')
    connection.dispose()
    fetcher.mockRejectedValue(new Error('offline'))
    const restored = create()
    await restored.load()
    await restored.apply()
    expect(restored.status().profileCount).toBe(1)
    expect(core).toHaveBeenLastCalledWith(
      'configure',
      expect.objectContaining({
        scope: createHash('sha256')
          .update(JSON.stringify(['https://company.example', 'company-id', 'admin-id']))
          .digest('hex'),
        profiles: snapshot.profiles,
      }),
    )
    expect((await restored.execute({ action: 'sync' })).error).toContain('无法连接')
    expect(restored.status().engine?.enabled).toBe(true)
    await vi.advanceTimersByTimeAsync(120_000)
    expect(restored.status().session).toBe('expired')
    expect(restored.status().profileCount).toBe(1)
    await restored.apply()
    expect(restored.status().engine?.enabled).toBe(true)
  })
  it('401 and incompatible server updates preserve usable cache; clear stops using it but preserves login', async () => {
    const { connection, fetcher, create, core } = await fixture()
    await login(connection)
    await connection.execute({ action: 'sync' })
    fetcher
      .mockResolvedValueOnce(json({ ...account, expiresAt: expires() }))
      .mockResolvedValueOnce(json({ ...snapshot, modelId: 'future' }))
    expect((await connection.execute({ action: 'sync' })).error).toContain('不兼容')
    expect(connection.status().profileCount).toBe(1)
    fetcher.mockResolvedValueOnce(json({}, 401))
    expect((await connection.execute({ action: 'sync' })).session).toBe('expired')
    expect(connection.status().profileCount).toBe(1)
    await connection.execute({ action: 'clear' })
    expect(connection.status().identity).toEqual(account)
    expect(core).toHaveBeenLastCalledWith('configure', {
      scope: null,
      modelId: VOICEPRINT_MODEL,
      profiles: [],
    })
    const restarted = create()
    await restarted.load()
    expect(restarted.status().profileCount).toBe(0)
    expect(restarted.status().identity).toEqual(account)
  })
  it('logout clears durable credentials and defeats an older synchronization completing later', async () => {
    const { connection, create, fetcher, core } = await fixture()
    await login(connection)
    await connection.execute({ action: 'sync' })
    let resolve!: (value: Response) => void
    fetcher.mockResolvedValueOnce(json({ ...account, expiresAt: expires() }))
    fetcher.mockImplementationOnce(
      () =>
        new Promise<Response>((done) => {
          resolve = done
        }),
    )
    const synchronizing = connection.execute({ action: 'sync' })
    await vi.waitFor(() => expect(resolve).toBeDefined())
    await connection.execute({ action: 'logout' })
    resolve(json(snapshot))
    await synchronizing
    expect(connection.status()).toMatchObject({
      session: 'guest',
      profileCount: 0,
      identity: null,
      error: null,
    })
    expect(core).toHaveBeenLastCalledWith('configure', {
      scope: null,
      modelId: VOICEPRINT_MODEL,
      profiles: [],
    })
    const restarted = create()
    await restarted.load()
    expect(restarted.status()).toMatchObject({ session: 'guest', profileCount: 0, identity: null })
  })
  it('polls actual core processing state and clear remains durable if secure storage becomes unavailable', async () => {
    const { connection, core, create } = await fixture()
    await login(connection)
    await connection.execute({ action: 'sync' })
    core.mockResolvedValueOnce({
      enabled: true,
      profileCount: 1,
      modelId: VOICEPRINT_MODEL,
      state: 'processing',
      error: null,
    })
    expect((await connection.execute({ action: 'status' })).engine?.state).toBe('processing')
    const unavailable = vi.spyOn(secrets, 'isAsyncEncryptionAvailable').mockResolvedValue(false)
    try {
      const result = await connection.execute({ action: 'clear' })
      expect(result.error).toContain('安全存储不可用')
      expect(result.profileCount).toBe(0)
      expect(core).toHaveBeenLastCalledWith('configure', {
        scope: null,
        modelId: VOICEPRINT_MODEL,
        profiles: [],
      })
    } finally {
      unavailable.mockRestore()
    }
    const restarted = create()
    await restarted.load()
    expect(restarted.status().profileCount).toBe(0)
  })
  it('limits response bodies before accepting a snapshot and retains the previous complete cache', async () => {
    const { connection, fetcher } = await fixture()
    await login(connection)
    await connection.execute({ action: 'sync' })
    fetcher
      .mockResolvedValueOnce(json({ ...account, expiresAt: expires() }))
      .mockResolvedValueOnce(
        new Response('{}', { headers: { 'content-length': String(49 * 1024 * 1024) } }),
      )
    expect((await connection.execute({ action: 'sync' })).error).toContain('数据过大')
    expect(connection.status().profileCount).toBe(1)
  })
  it('cancelled browser authorization cannot write its late response back', async () => {
    const { connection, fetcher, create } = await fixture()
    const original = fetcher.getMockImplementation()!
    let resolve!: (value: Response) => void
    fetcher.mockImplementation((input, init) =>
      String(input).endsWith('/exchange')
        ? new Promise<Response>((done) => {
            resolve = done
          })
        : original(input, init),
    )
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] })
    await connection.execute({ action: 'login' })
    await vi.advanceTimersByTimeAsync(2000)
    expect(resolve).toBeDefined()
    await connection.execute({ action: 'cancel' })
    resolve(json({ ...account, token, expiresAt: expires() }))
    await vi.advanceTimersByTimeAsync(50)
    expect(connection.status().session).toBe('guest')
    const restarted = create()
    await restarted.load()
    expect(restarted.status().identity).toBeNull()
  })
})
