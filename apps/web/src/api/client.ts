import type { SupportDiagnostics } from '@paa/api-contracts'
import { captureDiagnostics } from '@web/lib/diagnostics'

let csrf = ''

export let epoch = 0

let expired = false

const requests = new Set<AbortController>()

export const setCsrf = (value: string) => {
  csrf = value
  expired = false
  epoch++
  requests.forEach((controller) => controller.abort())
}

export function expireSession() {
  if (expired) return
  expired = true
  csrf = ''
  epoch++
  requests.forEach((controller) => controller.abort())
  if (typeof window !== 'undefined') window.dispatchEvent(new Event('paa-session-expired'))
}

export class ApiError extends Error {
  public diagnostics: SupportDiagnostics
  public retryAt: number
  public fields: string[] = []
  public fieldErrors: Record<string, string> = {}
  constructor(
    public status: number,
    public code: string,
    message: string,
    public category: NonNullable<SupportDiagnostics['category']> = 'unknown',
    public requestId: string | null = null,
    public retryAfter: number | null = null,
    diagnostics = captureDiagnostics(),
  ) {
    super(message)
    this.name = 'ApiError'
    this.retryAt = retryAfter ? Date.now() + retryAfter * 1000 : 0
    this.diagnostics = { ...diagnostics, category, httpStatus: status || null, requestId }
  }
  get retryable() {
    return !['unauthorized', 'forbidden', 'cancelled'].includes(this.category)
  }
}

export const cancelledRequest = () => new ApiError(0, 'cancelled', '', 'cancelled')

export const isCancelled = (error: unknown) =>
  error instanceof ApiError && error.category === 'cancelled'

export const requestBudget = (path: string) =>
  path === '/uploads' || path.startsWith('/settings/voiceprints/')
    ? 120000
    : /^\/settings\/model-services\/(test|models)$/.test(path)
      ? 180000
      : 30000

const uuid = (value: unknown): string | null =>
  typeof value === 'string' &&
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)
    ? value
    : null

// Only structured first-party validation/conflict messages are shown. Generic
// server/proxy/provider failures never expose arbitrary upstream text.
function businessMessage(value: unknown, fallback: string) {
  return typeof value === 'string' &&
    value.length <= 220 &&
    /[\u3400-\u9fff]/.test(value) &&
    !/[<>\r\n]|https?:\/\/|traceback|stack|authorization|cookie|api[_ -]?key|bearer|sk-[a-z0-9]/i.test(
      value,
    )
    ? value
    : fallback
}

function responseFailure(
  status: number,
  code: string,
  message: unknown,
  retryAfter: number | null,
) {
  if (status === 401)
    return {
      category: 'unauthorized' as const,
      message:
        code === 'invalid_credentials'
          ? '账号或密码不正确，请重新输入。'
          : '登录已过期，请重新登录。当前聊天草稿会在原账号验证后恢复。',
    }
  if (status === 403)
    return {
      category: 'forbidden' as const,
      message: businessMessage(message, '没有访问权限，请联系公司管理员。'),
    }
  if (status === 429)
    return {
      category: 'rate_limited' as const,
      message: retryAfter ? `请求较多，请等待 ${retryAfter} 秒后再试。` : '请求较多，请稍后再试。',
    }
  if (status >= 500) return { category: 'server' as const, message: '服务暂时不可用，请稍后重试。' }
  if (status === 409)
    return {
      category: 'conflict' as const,
      message: businessMessage(message, '内容已变化，请读取最新版本后继续。'),
    }
  return {
    category: 'validation' as const,
    message: businessMessage(
      message,
      status === 404 ? '内容不存在或已不可访问。' : '请求未完成，请检查输入后重试。',
    ),
  }
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
  format: 'json' | 'bytes' = 'json',
): Promise<T> {
  const auth = path.startsWith('/auth/')
  if (!auth && expired) throw cancelledRequest()
  const generation = epoch
  const diagnostics = captureDiagnostics()
  const headers = new Headers(options.headers)
  if (options.body && !(options.body instanceof FormData))
    headers.set('Content-Type', 'application/json')
  if (options.method && options.method !== 'GET') headers.set('X-CSRF-Token', csrf)
  const controller = new AbortController()
  requests.add(controller)
  let timedOut = false
  const abort = () => controller.abort()
  options.signal?.addEventListener('abort', abort, { once: true })
  if (options.signal?.aborted) controller.abort()
  const timeout = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, requestBudget(path))
  try {
    const response = await fetch(`/api/v1${path}`, {
      ...options,
      headers,
      signal: controller.signal,
      credentials: 'same-origin',
    })
    if (generation !== epoch || options.signal?.aborted) throw cancelledRequest()
    if (controller.signal.aborted) throw new DOMException('Aborted', 'AbortError')
    if (response.ok && format === 'bytes') {
      const bytes = await response.arrayBuffer()
      if (controller.signal.aborted) throw new DOMException('Aborted', 'AbortError')
      if (generation !== epoch || options.signal?.aborted) throw cancelledRequest()
      if (typeof window !== 'undefined') window.dispatchEvent(new Event('paa-request-connected'))
      return bytes as T
    }
    const text = await response.text()
    if (controller.signal.aborted) throw new DOMException('Aborted', 'AbortError')
    if (generation !== epoch || options.signal?.aborted) throw cancelledRequest()
    let body: unknown
    try {
      body = text ? JSON.parse(text) : null
    } catch {
      body = null
    }
    const envelope = body && typeof body === 'object' && 'error' in body ? body.error : null
    const detail =
      envelope && typeof envelope === 'object' ? (envelope as Record<string, unknown>) : {}
    const requestId = uuid(detail.requestId) ?? uuid(response.headers.get('X-Request-ID'))
    if (!response.ok) {
      const code =
        typeof detail.code === 'string' && /^[a-z0-9_]{1,80}$/.test(detail.code)
          ? detail.code
          : 'failed'
      const after = Number(response.headers.get('Retry-After') ?? detail.retryAfter)
      const retryAfter =
        Number.isFinite(after) && after > 0 ? Math.min(Math.ceil(after), 86400) : null
      const failure = responseFailure(response.status, code, detail.message, retryAfter)
      if (path === '/auth/login' && response.status === 401)
        failure.message = '账号或密码不正确，请重新输入。'
      const error = new ApiError(
        response.status,
        code,
        failure.message,
        failure.category,
        requestId,
        retryAfter,
        diagnostics,
      )
      if (Array.isArray(detail.fields))
        error.fields = detail.fields
          .filter(
            (field): field is string =>
              typeof field === 'string' && /^[a-zA-Z0-9_.]{1,120}$/.test(field),
          )
          .slice(0, 50)
      if (
        detail.fieldErrors &&
        typeof detail.fieldErrors === 'object' &&
        !Array.isArray(detail.fieldErrors)
      )
        error.fieldErrors = Object.fromEntries(
          Object.entries(detail.fieldErrors)
            .filter(([field]) => /^[a-zA-Z][a-zA-Z0-9_.]{0,119}$/.test(field))
            .slice(0, 50)
            .map(([field, message]) => [
              field,
              businessMessage(message, '输入不符合要求，请检查后重试。'),
            ]),
        )
      if (response.status === 401 && path !== '/auth/login') expireSession()
      if (
        response.status === 403 &&
        (code === 'business_access_changed' ||
          (typeof detail.message === 'string' && detail.message.startsWith('账号权限已变化'))) &&
        typeof window !== 'undefined'
      ) {
        window.dispatchEvent(new CustomEvent('paa-access-forbidden', { detail: { path, code } }))
        if (typeof detail.message === 'string' && detail.message.startsWith('账号权限已变化'))
          expireSession()
      }
      throw error
    }
    if (response.status === 204) return undefined as T
    if (body === null || typeof body !== 'object')
      throw new ApiError(
        response.status,
        'invalid_response',
        '服务返回了无法读取的结果，请稍后重试。',
        'invalid_response',
        requestId,
        null,
        diagnostics,
      )
    if (typeof window !== 'undefined') window.dispatchEvent(new Event('paa-request-connected'))
    return body as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (generation !== epoch || options.signal?.aborted || (controller.signal.aborted && !timedOut))
      throw cancelledRequest()
    const failure = new ApiError(
      0,
      timedOut ? 'timeout' : 'network',
      timedOut
        ? '等待响应超时，请稍后重试。提交操作的结果可能尚未返回。'
        : '无法连接服务，请检查网络后重试。',
      timedOut ? 'timeout' : 'network',
      null,
      null,
      diagnostics,
    )
    if (typeof window !== 'undefined')
      window.dispatchEvent(new CustomEvent('paa-connection-error', { detail: failure.message }))
    throw failure
  } finally {
    clearTimeout(timeout)
    options.signal?.removeEventListener('abort', abort)
    requests.delete(controller)
  }
}

export const write = <T>(path: string, body: unknown, method = 'POST', key?: string) =>
  api<T>(path, {
    method,
    body: JSON.stringify(body),
    headers: key ? { 'Idempotency-Key': key } : undefined,
  })
