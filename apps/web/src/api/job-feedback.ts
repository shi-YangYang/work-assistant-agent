import type { Job, JobFeedback, Report } from '@paa/api-contracts'
import { api, ApiError, expireSession, isCancelled } from '@web/api/client'

const terminalJob = (state: string) => !['queued', 'running'].includes(state)

export const reportNeedsPolling = (report: Pick<Report, 'historical' | 'job'>) =>
  !report.historical && !!report.job && !terminalJob(report.job.state)

export function acceptFeedback(
  current: JobFeedback | null,
  incoming: JobFeedback,
  jobId: string,
): JobFeedback | null {
  if (incoming.jobId !== jobId) return current
  if (current && current.jobId === jobId) {
    for (const field of ['attempt', 'fence', 'seq'] as const) {
      if (incoming[field] < current[field]) return current
      if (incoming[field] > current[field]) return incoming
    }
    if (incoming.updatedAt < current.updatedAt) return current
    // Cards can change independently of the worker's feedback version. Match the
    // server's snapshot identity so retries deduplicate without hiding card updates.
    if (
      incoming.updatedAt === current.updatedAt &&
      incoming.state === current.state &&
      JSON.stringify(incoming.actions ?? []) === JSON.stringify(current.actions ?? []) &&
      JSON.stringify(incoming.nodes ?? []) === JSON.stringify(current.nodes ?? [])
    )
      return current
  }
  return incoming
}

export function visibleFeedback(job: Job | null, value: JobFeedback | null) {
  if (
    !job ||
    !value ||
    value.jobId !== job.id ||
    value.attempt < (job.attempt ?? 0) ||
    value.fence < (job.fence ?? 0)
  )
    return null
  if (['succeeded', 'awaiting_input', 'cancelled'].includes(job.state)) return null
  if (
    terminalJob(job.state) &&
    value.attempt === (job.attempt ?? 0) &&
    value.fence === (job.fence ?? 0)
  )
    return { ...value, state: job.state, error: job.error }
  return value
}

export const stageNames: Record<string, string> = {
  queued: '已发送，正在排队…',
  preparing: '正在准备处理…',
  parsing: '正在解析文件…',
  transcribing: '正在识别语音…',
  searching: '正在查询资料…',
  generating: '正在生成回复…',
  operating: '操作结果已更新，正在继续处理…',
  reviewing: '正在核对答复…',
  complete: '已完成',
}

export function subscribeJobFeedback(
  jobId: string | null,
  state: string | undefined,
  attempt: number,
  fence: number,
  receiveValue: (value: JobFeedback | null) => void,
  setError: (message: string) => void,
  refresh: () => void,
) {
  if (!jobId || state === 'succeeded' || state === 'awaiting_input' || state === 'cancelled') return
  let closed = false
  let polling = false
  let completed = false
  let retryAt = 0
  let source: EventSource | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  const controller = new AbortController()
  const receive = (incoming: JobFeedback) => {
    if (closed || incoming.attempt < attempt || incoming.fence < fence) return
    receiveValue(incoming)
    setError('')
    if (terminalJob(incoming.state)) {
      completed = true
      source?.close()
      clearTimeout(timer)
      refresh()
    }
  }
  const stop = (message: string, status?: number) => {
    if (closed) return
    closed = true
    controller.abort()
    source?.close()
    clearTimeout(timer)
    receiveValue(null)
    setError(message)
    if (status === 401) expireSession()
    else if (status === 403 || status === 404) refresh()
  }
  const poll = async () => {
    if (closed || polling || completed || document.hidden) return
    const remaining = retryAt - Date.now()
    if (remaining > 0) {
      clearTimeout(timer)
      timer = setTimeout(poll, remaining)
      return
    }
    clearTimeout(timer)
    polling = true
    try {
      const incoming = await api<JobFeedback>(`/jobs/${jobId}/feedback`, {
        signal: controller.signal,
      })
      if (closed) return
      retryAt = 0
      receive(incoming)
      if (!terminalJob(incoming.state)) timer = setTimeout(poll, 5000)
    } catch (failure) {
      if (closed || isCancelled(failure)) return
      if (failure instanceof ApiError && [401, 403, 404].includes(failure.status)) {
        stop(failure.message, failure.status)
        return
      }
      setError('连接中断，正在恢复处理状态…')
      retryAt =
        failure instanceof ApiError && (failure.status === 429 || failure.retryAfter)
          ? failure.retryAt || Date.now() + 5000
          : 0
      timer = setTimeout(poll, retryAt ? Math.max(0, retryAt - Date.now()) : 5000)
    } finally {
      polling = false
    }
  }
  if (state && terminalJob(state)) void poll()
  else {
    source = new EventSource(`/api/v1/jobs/${jobId}/events`)
    source.addEventListener('snapshot', (event) => {
      try {
        receive(JSON.parse((event as MessageEvent).data) as JobFeedback)
      } catch {
        setError('实时状态读取失败，正在恢复…')
      }
    })
    source.addEventListener('unavailable', (event) => {
      try {
        const failure = JSON.parse((event as MessageEvent).data) as { status: number }
        stop(
          failure.status === 401 ? '登录已过期，请重新登录。' : '处理状态已不可访问，请重新加载。',
          failure.status,
        )
      } catch {
        source?.close()
        void poll()
      }
    })
    source.onopen = () => {
      if (!closed) {
        setError('')
        clearTimeout(timer)
      }
    }
    source.onerror = () => {
      if (closed || completed) return
      source?.close()
      source = undefined
      setError(navigator.onLine ? '实时连接中断，正在恢复…' : '网络已断开，联网后恢复处理状态。')
      clearTimeout(timer)
      timer = setTimeout(poll, 1000)
    }
  }
  const recover = () => {
    if (!document.hidden && !source) void poll()
  }
  window.addEventListener('online', recover)
  document.addEventListener('visibilitychange', recover)
  return () => {
    window.removeEventListener('online', recover)
    document.removeEventListener('visibilitychange', recover)
    closed = true
    controller.abort()
    source?.close()
    clearTimeout(timer)
  }
}
