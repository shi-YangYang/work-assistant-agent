import { useCallback, useEffect, useState } from 'react'

let csrf = ''
export const setCsrf = (value: string) => {
  csrf = value
}
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message)
  }
}
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !(options.body instanceof FormData))
    headers.set('Content-Type', 'application/json')
  if (options.method && options.method !== 'GET') headers.set('X-CSRF-Token', csrf)
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    headers,
    credentials: 'same-origin',
  })
  const body = await response.json()
  if (!response.ok) {
    if (response.status === 401 && path !== '/auth/login')
      window.dispatchEvent(new Event('paa-session-expired'))
    throw new ApiError(
      response.status,
      body.error?.code ?? 'failed',
      body.error?.message ?? '请求未完成，请重试',
    )
  }
  return body as T
}
export const write = <T>(path: string, body: unknown, method = 'POST', key?: string) =>
  api<T>(path, {
    method,
    body: JSON.stringify(body),
    headers: key ? { 'Idempotency-Key': key } : undefined,
  })
export function useResource<T>(path: string | null, interval = 0) {
  const [loaded, setLoaded] = useState<{ path: string; data: T } | null>(null)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const refresh = useCallback(() => setRevision((n) => n + 1), [])
  useEffect(() => {
    if (!path) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const load = async () => {
      try {
        const result = await api<T>(path, { signal: controller.signal })
        if (!controller.signal.aborted) {
          setLoaded({ path, data: result })
          setError('')
        }
      } catch (e) {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : '连接失败')
      }
      if (interval && !controller.signal.aborted)
        timer = setTimeout(load, document.hidden ? Math.max(interval, 30000) : interval)
    }
    void load()
    return () => {
      controller.abort()
      clearTimeout(timer)
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
