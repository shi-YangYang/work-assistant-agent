import { useCallback, useEffect, useRef, useState } from 'react'
import type { SupportDiagnostics } from '@paa/api-contracts'
import { captureDiagnostics } from './diagnostics'

let csrf = ''
let epoch = 0
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
export function useRetryWait(error: unknown) {
  const retryAt = error instanceof ApiError ? error.retryAt : 0
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    if (!retryAt || retryAt <= Date.now()) return
    const timer = setInterval(() => {
      setNow(Date.now())
      if (Date.now() >= retryAt) clearInterval(timer)
    }, 1000)
    return () => clearInterval(timer)
  }, [retryAt])
  return retryAt && error instanceof ApiError
    ? Math.min(error.retryAfter ?? 0, Math.max(0, Math.ceil((retryAt - now) / 1000)))
    : 0
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
export function useResource<T>(path: string | null, interval = 0) {
  const [loaded, setLoaded] = useState<{ path: string; data: T } | null>(null)
  const [error, setError] = useState<Error | string>('')
  const [revision, setRevision] = useState(0)
  const retry = useRef({ path, epoch, at: 0 })
  const refresh = useCallback(() => setRevision((n) => n + 1), [])
  useEffect(() => {
    if (retry.current.path !== path || retry.current.epoch !== epoch)
      retry.current = { path, epoch, at: 0 }
    if (!path) return
    const waiting = retry.current
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    let loading = false
    let unavailable = false
    const load = async () => {
      if (loading || controller.signal.aborted || unavailable) return
      if (waiting.epoch !== epoch) {
        waiting.epoch = epoch
        waiting.at = 0
      }
      const remaining = waiting.at - Date.now()
      if (remaining > 0) {
        clearTimeout(timer)
        timer = setTimeout(load, remaining)
        return
      }
      loading = true
      let nextDelay = interval
      clearTimeout(timer)
      try {
        const result = await api<T>(path, { signal: controller.signal })
        if (!controller.signal.aborted) {
          waiting.at = 0
          setLoaded({ path, data: result })
          setError('')
        }
      } catch (e) {
        if (!controller.signal.aborted && !isCancelled(e)) {
          setError(e instanceof Error ? e : '连接失败')
          if (e instanceof ApiError && e.status === 429) {
            waiting.at = e.retryAt || Date.now() + 5000
            nextDelay = Math.max(interval, waiting.at - Date.now())
          }
          if (
            e instanceof ApiError &&
            ([401, 403, 404].includes(e.status) ||
              e.code === 'business_access_changed' ||
              e.code === 'source_changed')
          ) {
            setLoaded(null)
            unavailable = true
          }
        }
      } finally {
        loading = false
      }
      if (interval && !controller.signal.aborted && !unavailable)
        timer = setTimeout(load, document.hidden ? Math.max(nextDelay, 30000) : nextDelay)
    }
    const recover = () => {
      if (!document.hidden) void load()
    }
    void load()
    window.addEventListener('online', recover)
    document.addEventListener('visibilitychange', recover)
    return () => {
      controller.abort()
      clearTimeout(timer)
      window.removeEventListener('online', recover)
      document.removeEventListener('visibilitychange', recover)
    }
  }, [path, interval, revision])
  return { data: loaded?.path === path ? loaded.data : null, error, refresh }
}
export const dateLabel = (value: string) =>
  new Date(value).toLocaleString('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
export const todayIn = (timezone: string) =>
  new Intl.DateTimeFormat('en-CA', {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date())
