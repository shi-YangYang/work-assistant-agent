import { createHash, randomBytes } from 'node:crypto'
import { mkdir, readFile, rename, rm, stat, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import type {
  CompanyIdentity,
  CompanyRequest,
  CompanyStatus,
  VoiceprintStatus,
} from '../shared/company-contracts'
import type { SecretStorage } from './summary-settings'

export const VOICEPRINT_MODEL = 'wespeaker-resnet34-lm:6f10ff60898a1d18:pcm16k-v1'
const MAX_BYTES = 48 * 1024 * 1024
export type VoiceprintProfile = { memberId: string; name: string; templates: number[][] }
export type VoiceprintConfiguration = {
  scope: string | null
  modelId: string
  profiles: VoiceprintProfile[]
}
type Snapshot = { modelId: string; revision: string; profiles: VoiceprintProfile[] }
type Saved = {
  version: 1
  serverUrl: string
  token: string | null
  expiresAt: string | null
  identity: CompanyIdentity | null
  snapshot: Snapshot | null
  syncedAt: string | null
}
type Pending = { requestId: string; verifier: string; expires: number; generation: number }
class CompanyError extends Error {
  constructor(
    message: string,
    readonly status = 0,
  ) {
    super(message)
  }
}
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw new CompanyError('公司服务返回的数据无效。')
  return value as Record<string, unknown>
}
function text(value: unknown, maximum = 160): string {
  if (
    typeof value !== 'string' ||
    !value.trim() ||
    value.length > maximum ||
    [...value].some(
      (character) =>
        character.charCodeAt(0) < 32 ||
        (character.charCodeAt(0) >= 127 && character.charCodeAt(0) < 160),
    )
  )
    throw new CompanyError('公司服务返回的数据无效。')
  return value
}
function date(value: unknown): string {
  const result = text(value, 64)
  if (!Number.isFinite(Date.parse(result))) throw new CompanyError('公司服务返回的有效期无效。')
  return result
}
export function companyOrigin(value: string): string {
  let url: URL
  try {
    url = new URL(value.trim())
  } catch {
    throw new CompanyError('请填写完整的公司 Web 地址。')
  }
  if (
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    !['/', '/api/v1', '/api/v1/'].includes(url.pathname) ||
    (url.protocol !== 'https:' &&
      !(url.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)))
  )
    throw new CompanyError('公司地址须为 HTTPS 根地址；本机开发可使用 http://127.0.0.1:5174。')
  return url.origin
}
function identity(value: unknown): CompanyIdentity {
  const data = object(value),
    member = object(data.member),
    company = object(data.company)
  if (member.role !== 'admin' && member.role !== 'employee')
    throw new CompanyError('公司账号角色无效。')
  return {
    member: { id: text(member.id), name: text(member.name), role: member.role },
    company: { id: text(company.id), name: text(company.name) },
  }
}
export function voiceprintSnapshot(value: unknown): Snapshot {
  const data = object(value)
  if (data.modelId !== VOICEPRINT_MODEL)
    throw new CompanyError('公司声纹版本与当前桌面不兼容，请更新应用后重新同步。')
  if (!Array.isArray(data.profiles) || data.profiles.length > 500)
    throw new CompanyError('公司声纹数量超过支持范围。')
  const members = new Set<string>()
  const profiles = data.profiles.map((value) => {
    const item = object(value),
      memberId = text(item.memberId, 128),
      name = text(item.name, 100)
    if (
      members.has(memberId) ||
      !Array.isArray(item.templates) ||
      !item.templates.length ||
      item.templates.length > 12
    )
      throw new CompanyError('公司声纹模板无效。')
    members.add(memberId)
    const templates = item.templates.map((vector) => {
      if (
        !Array.isArray(vector) ||
        vector.length !== 256 ||
        !vector.every((n) => typeof n === 'number' && Number.isFinite(n))
      )
        throw new CompanyError('公司声纹特征无效。')
      const norm = Math.sqrt(vector.reduce((sum, n) => sum + n * n, 0))
      if (norm < 0.98 || norm > 1.02) throw new CompanyError('公司声纹特征无效。')
      return vector as number[]
    })
    return { memberId, name, templates }
  })
  return { modelId: VOICEPRINT_MODEL, revision: text(data.revision, 256), profiles }
}
export class CompanyConnection {
  private saved: Saved = {
    version: 1,
    serverUrl: '',
    token: null,
    expiresAt: null,
    identity: null,
    snapshot: null,
    syncedAt: null,
  }
  private error: string | null = null
  private engine: VoiceprintStatus | null = null
  private pending: Pending | null = null
  private timer: ReturnType<typeof setTimeout> | undefined
  private generation = 0
  private busy = false
  private expired = false
  private disk: Promise<unknown> = Promise.resolve()
  private applying: Promise<unknown> = Promise.resolve()
  private controllers = new Set<AbortController>()
  constructor(
    private readonly root: string,
    private readonly secrets: SecretStorage,
    private readonly core: (
      action: 'configure' | 'status',
      config?: VoiceprintConfiguration,
    ) => Promise<VoiceprintStatus>,
    private readonly openBrowser: (url: string) => Promise<void>,
    private readonly changed: (status: CompanyStatus) => void = () => {},
    private readonly fetcher: typeof fetch = fetch,
  ) {}
  status(): CompanyStatus {
    return {
      serverUrl: this.saved.serverUrl,
      session: this.pending
        ? 'authorizing'
        : this.saved.identity
          ? this.expired || (this.saved.expiresAt && Date.parse(this.saved.expiresAt) <= Date.now())
            ? 'expired'
            : 'signed-in'
          : 'guest',
      identity: this.saved.identity ? structuredClone(this.saved.identity) : null,
      busy: this.busy,
      error: this.error,
      syncedAt: this.saved.syncedAt,
      profileCount: this.saved.snapshot?.profiles.length ?? 0,
      engine: this.engine ? { ...this.engine } : null,
    }
  }
  private emit(): void {
    this.changed(this.status())
  }
  async load(): Promise<void> {
    const path = join(this.root, 'company-connection.enc')
    try {
      if ((await stat(path)).size > MAX_BYTES * 2) throw new Error('size')
      if (!(await this.secrets.isAsyncEncryptionAvailable())) throw new Error('encryption')
      const { result } = await this.secrets.decryptStringAsync(await readFile(path))
      const value = object(JSON.parse(result))
      if (value.version !== 1 || typeof value.serverUrl !== 'string') throw new Error('state')
      const account = value.identity === null ? null : identity(value.identity)
      const token = value.token === null ? null : text(value.token, 512)
      const snapshot = value.snapshot === null ? null : voiceprintSnapshot(value.snapshot)
      if ((!account && (token || snapshot)) || (account?.member.role !== 'admin' && snapshot))
        throw new Error('scope')
      this.saved = {
        version: 1,
        serverUrl: value.serverUrl ? companyOrigin(value.serverUrl) : '',
        token,
        expiresAt: value.expiresAt === null ? null : date(value.expiresAt),
        identity: account,
        snapshot,
        syncedAt: value.syncedAt === null ? null : date(value.syncedAt),
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT')
        this.error = '公司连接缓存无法读取，请重新登录；原有会议不受影响。'
    }
    this.emit()
  }
  private async persist(generation: number): Promise<void> {
    const state = JSON.stringify(this.saved)
    const operation = this.disk
      .catch(() => undefined)
      .then(async () => {
        if (generation !== this.generation) return
        const path = join(this.root, 'company-connection.enc')
        if (!this.saved.identity && !this.saved.serverUrl) {
          await rm(path, { force: true })
          return
        }
        if (!(await this.secrets.isAsyncEncryptionAvailable()))
          throw new CompanyError('系统安全存储不可用，无法保存公司登录和声纹。')
        const encrypted = await this.secrets.encryptStringAsync(state)
        if (generation !== this.generation) return
        await mkdir(this.root, { recursive: true })
        const temporary = `${path}.tmp`
        try {
          await writeFile(temporary, encrypted, { mode: 0o600 })
          if (generation === this.generation) await rename(temporary, path)
        } finally {
          await rm(temporary, { force: true })
        }
      })
    this.disk = operation
    await operation
  }
  private async erase(): Promise<void> {
    const operation = this.disk
      .catch(() => undefined)
      .then(() => rm(join(this.root, 'company-connection.enc'), { force: true }))
    this.disk = operation
    await operation
  }
  async apply(): Promise<void> {
    const generation = this.generation
    const snapshot = this.saved.snapshot
    const config: VoiceprintConfiguration = {
      scope:
        snapshot && this.saved.identity
          ? createHash('sha256')
              .update(
                JSON.stringify([
                  this.saved.serverUrl,
                  this.saved.identity.company.id,
                  this.saved.identity.member.id,
                ]),
              )
              .digest('hex')
          : null,
      modelId: VOICEPRINT_MODEL,
      profiles: snapshot?.profiles ?? [],
    }
    const operation = this.applying
      .catch(() => undefined)
      .then(async () => {
        if (generation !== this.generation) return
        try {
          const engine = await this.core('configure', config)
          if (generation === this.generation) this.engine = engine
        } catch {
          if (generation === this.generation)
            this.engine = {
              enabled: false,
              profileCount: 0,
              modelId: VOICEPRINT_MODEL,
              state: 'failed',
              error: '本地识别尚未就绪，请检查本地核心连接后重试。',
            }
        }
        this.emit()
      })
    this.applying = operation
    await operation
  }
  coreStopped(): void {
    this.engine = null
    this.emit()
  }
  private invalidate(): number {
    this.generation++
    if (this.timer) clearTimeout(this.timer)
    this.timer = undefined
    this.pending = null
    this.busy = false
    for (const controller of this.controllers) controller.abort()
    this.controllers.clear()
    return this.generation
  }
  dispose(): void {
    this.invalidate()
  }
  private async request(
    path: string,
    options: { body?: object; token?: string; server?: string; large?: boolean } = {},
  ): Promise<{ status: number; data: unknown }> {
    const controller = new AbortController()
    this.controllers.add(controller)
    const timeout = setTimeout(() => controller.abort(), 20_000)
    try {
      const response = await this.fetcher(
        `${options.server ?? this.saved.serverUrl}/api/v1/desktop/${path}`,
        {
          method: options.body ? 'POST' : 'GET',
          redirect: 'error',
          signal: controller.signal,
          headers: {
            Accept: 'application/json',
            ...(options.body ? { 'Content-Type': 'application/json' } : {}),
            ...(options.token ? { Authorization: `Bearer ${options.token}` } : {}),
          },
          ...(options.body ? { body: JSON.stringify(options.body) } : {}),
        },
      )
      if (response.redirected || (response.status >= 300 && response.status < 400))
        throw new CompanyError('公司服务不允许重定向，请填写最终服务地址。')
      const limit = options.large ? MAX_BYTES : 64 * 1024
      if (Number(response.headers.get('content-length') ?? 0) > limit)
        throw new CompanyError('公司服务返回的数据过大。')
      const reader = response.body?.getReader()
      if (!reader) throw new CompanyError('公司服务没有返回有效数据。')
      const chunks: Uint8Array[] = []
      let size = 0
      try {
        for (;;) {
          const next = await reader.read()
          if (next.done) break
          size += next.value.byteLength
          if (size > limit) throw new CompanyError('公司服务返回的数据过大。')
          chunks.push(next.value)
        }
      } finally {
        await reader.cancel().catch(() => undefined)
      }
      if (!response.ok) {
        const messages: Record<number, string> = {
          401: '公司登录已过期，请重新登录；已下载声纹仍可离线使用。',
          403: '当前账号无权同步公司声纹，请使用公司管理员账号。',
          410: '登录授权已过期或已取消，请重新登录。',
          429: '请求过于频繁，请稍后重试。',
        }
        throw new CompanyError(
          messages[response.status] ?? '公司服务暂不可用，请检查地址或稍后重试。',
          response.status,
        )
      }
      try {
        return { status: response.status, data: JSON.parse(Buffer.concat(chunks).toString('utf8')) }
      } catch {
        throw new CompanyError('公司服务返回的数据无效，请确认填写的是公司 Web 地址。')
      }
    } catch (error) {
      if (error instanceof CompanyError) throw error
      throw new CompanyError('无法连接公司服务，请检查网络、地址与证书；已下载声纹可继续使用。')
    } finally {
      clearTimeout(timeout)
      this.controllers.delete(controller)
    }
  }
  private schedule(): void {
    this.timer = setTimeout(() => {
      void this.poll()
    }, 2000)
  }
  private async poll(): Promise<void> {
    const pending = this.pending
    if (!pending || pending.generation !== this.generation) return
    if (pending.expires <= Date.now()) {
      this.pending = null
      this.error = '登录授权已过期，请重新登录。'
      this.emit()
      return
    }
    try {
      const response = await this.request('login/exchange', {
        body: { requestId: pending.requestId, verifier: pending.verifier },
      })
      if (pending.generation !== this.generation) return
      if (response.status === 202 && object(response.data).state === 'pending') {
        this.schedule()
        return
      }
      const value = object(response.data),
        account = identity(value),
        token = text(value.token, 512),
        expiresAt = date(value.expiresAt)
      if (Date.parse(expiresAt) <= Date.now()) throw new CompanyError('公司服务返回的登录已过期。')
      const same =
        this.saved.identity?.company.id === account.company.id &&
        this.saved.identity.member.id === account.member.id
      this.saved = {
        ...this.saved,
        token,
        expiresAt,
        identity: account,
        snapshot: same && account.member.role === 'admin' ? this.saved.snapshot : null,
        syncedAt: same && account.member.role === 'admin' ? this.saved.syncedAt : null,
      }
      this.pending = null
      this.expired = false
      this.error = null
      if (!same || account.member.role !== 'admin') await Promise.all([this.apply(), this.erase()])
      await this.persist(pending.generation)
      if (pending.generation !== this.generation) return
      await this.apply()
      this.emit()
    } catch (error) {
      if (pending.generation !== this.generation) return
      if (error instanceof CompanyError && error.status === 429) {
        this.schedule()
        return
      }
      this.error = error instanceof Error ? error.message : '登录未完成，请重试。'
      this.pending = null
      this.emit()
    }
  }
  private async login(serverUrl: string): Promise<void> {
    const server = companyOrigin(serverUrl),
      generation = this.invalidate()
    this.error = null
    this.busy = true
    try {
      if (this.saved.serverUrl !== server) {
        this.saved = {
          version: 1,
          serverUrl: server,
          token: null,
          expiresAt: null,
          identity: null,
          snapshot: null,
          syncedAt: null,
        }
        this.expired = false
        await Promise.all([this.erase(), this.apply()])
        await this.persist(generation)
      }
      this.emit()
      if (generation !== this.generation) return
      const info = object((await this.request('info', { server })).data)
      if (
        info.protocolVersion !== 1 ||
        typeof info.webOrigin !== 'string' ||
        companyOrigin(info.webOrigin) !== server
      )
        throw new CompanyError(
          '登录网页与公司地址不一致，请填写公司 Web 地址（本机开发为 http://127.0.0.1:5174）。',
        )
      if (generation !== this.generation) return
      const verifier = randomBytes(32).toString('base64url')
      const challenge = createHash('sha256').update(verifier).digest('base64url')
      const started = object((await this.request('login/start', { body: { challenge } })).data)
      if (generation !== this.generation) return
      const requestId = text(started.requestId, 128),
        expiresAt = date(started.expiresAt)
      if (!/^[A-Za-z0-9_-]{32,128}$/.test(requestId)) throw new CompanyError('公司登录请求无效。')
      const authorization = new URL(text(started.authorizationUrl, 2048))
      if (
        authorization.origin !== server ||
        authorization.pathname !== '/desktop/connect' ||
        authorization.username ||
        authorization.password ||
        authorization.hash ||
        [...authorization.searchParams.keys()].join() !== 'request' ||
        authorization.searchParams.get('request') !== requestId
      )
        throw new CompanyError('公司登录网页无效，已停止打开。')
      const expires = Date.parse(expiresAt)
      if (expires <= Date.now() || expires > Date.now() + 15 * 60_000)
        throw new CompanyError('公司登录请求有效期无效。')
      this.pending = { requestId, verifier, expires, generation }
      await this.openBrowser(authorization.href)
      if (generation === this.generation) this.schedule()
    } catch (error) {
      if (generation !== this.generation) return
      this.pending = null
      throw error
    } finally {
      if (generation === this.generation) {
        this.busy = false
        this.emit()
      }
    }
  }
  private async sync(): Promise<void> {
    if (this.busy || this.pending) throw new CompanyError('正在连接公司，请稍后重试。')
    if (!this.saved.token || !this.saved.identity || this.status().session === 'expired')
      throw new CompanyError('请先登录公司账号；已有声纹仍可离线使用。')
    if (this.saved.identity.member.role !== 'admin')
      throw new CompanyError('公司声纹仅限管理员同步。')
    const generation = this.generation,
      token = this.saved.token
    this.busy = true
    this.error = null
    this.emit()
    try {
      const remote = object((await this.request('me', { token })).data)
      if (generation !== this.generation) return
      const account = identity(remote)
      if (
        account.company.id !== this.saved.identity?.company.id ||
        account.member.id !== this.saved.identity.member.id ||
        account.member.role !== 'admin'
      )
        throw new CompanyError('公司账号身份或权限已改变，请重新登录。', 403)
      const snapshot = voiceprintSnapshot(
        (await this.request('voiceprints', { token, large: true })).data,
      )
      if (generation !== this.generation) return
      const previous = this.saved
      this.saved = {
        ...this.saved,
        snapshot,
        syncedAt: new Date().toISOString(),
        identity: account,
        expiresAt: date(remote.expiresAt),
      }
      try {
        await this.persist(generation)
      } catch (error) {
        if (generation === this.generation) this.saved = previous
        throw error
      }
      if (generation === this.generation) await this.apply()
    } catch (error) {
      if (generation !== this.generation) return
      if (error instanceof CompanyError && error.status === 401) this.expired = true
      throw error
    } finally {
      if (generation === this.generation) {
        this.busy = false
        this.emit()
      }
    }
  }
  async execute(input: CompanyRequest): Promise<CompanyStatus> {
    try {
      if (input.action === 'status') {
        const generation = this.generation
        if (this.saved.snapshot) {
          try {
            const engine = await this.core('status')
            if (generation === this.generation) this.engine = engine
          } catch {
            if (generation === this.generation) this.engine = null
          }
        }
        return this.status()
      }
      if (input.action === 'login') await this.login(input.serverUrl)
      else if (input.action === 'sync') await this.sync()
      else if (input.action === 'cancel') {
        this.invalidate()
        this.error = null
      } else if (input.action === 'logout' || input.action === 'clear') {
        const previous = this.saved,
          generation = this.invalidate()
        this.error = null
        this.saved = {
          ...this.saved,
          snapshot: null,
          syncedAt: null,
          ...(input.action === 'logout'
            ? { token: null, expiresAt: null, identity: null, serverUrl: '' }
            : {}),
        }
        await Promise.all([this.apply(), this.erase()])
        await this.persist(generation)
        // Local sign-out never waits for an unreachable company service.
        if (input.action === 'logout' && previous.token)
          void this.request('logout', {
            body: {},
            token: previous.token,
            server: previous.serverUrl,
          }).catch(() => undefined)
      }
      return this.status()
    } catch (error) {
      this.error = error instanceof Error ? error.message : '公司连接操作未完成。'
      return this.status()
    } finally {
      this.emit()
    }
  }
}
