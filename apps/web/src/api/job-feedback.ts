import type { Job, JobFeedback, Report } from '@paa/api-contracts'
import { api, ApiError, epoch, expireSession, isCancelled } from '@web/api/client'

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
    if (
      current.attempt === incoming.attempt &&
      terminalJob(current.state) &&
      !terminalJob(incoming.state)
    )
      return current
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
      JSON.stringify(incoming.interactions ?? []) === JSON.stringify(current.interactions ?? []) &&
      JSON.stringify(incoming.nodes ?? []) === JSON.stringify(current.nodes ?? []) &&
      JSON.stringify(incoming.taskOutcome ?? null) ===
        JSON.stringify(current.taskOutcome ?? null) &&
      JSON.stringify(incoming.contextUsage ?? null) === JSON.stringify(current.contextUsage ?? null)
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
  compacting: '正在压缩上下文…',
  complete: '已完成',
}

export const feedbackDisconnected = '连接已断开，任务可能仍在后台处理。'

function connectJobFeedback(
  jobId: string,
  attempt: number,
  fence: number,
  receiveValue: (value: JobFeedback | null) => boolean | void,
  setError: (message: string) => void,
  refresh: (feedback?: JobFeedback) => void,
  active: () => boolean,
) {
  let closed = false
  let completed = false
  let recovering = false
  let retryAt = 0
  let previousStage: string | undefined
  let source: EventSource | undefined
  let request: AbortController | undefined
  const closeSource = () => {
    source?.close()
    source = undefined
  }
  const receive = (incoming: JobFeedback) => {
    if (
      !active() ||
      closed ||
      completed ||
      incoming.jobId !== jobId ||
      incoming.attempt < attempt ||
      incoming.fence < fence
    )
      return
    if (receiveValue(incoming) === false) return
    const stageChanged = previousStage !== undefined && previousStage !== incoming.stage
    const completedMedia = previousStage === 'parsing' || previousStage === 'transcribing'
    previousStage = incoming.stage
    setError('')
    if (terminalJob(incoming.state)) {
      completed = true
      closeSource()
      refresh(incoming)
    } else if (stageChanged && completedMedia) {
      // Only media completion needs persisted transcript/extraction data. Search,
      // generation, operations and review are already represented by the stream.
      refresh(incoming)
    }
  }
  const stop = (message: string, status?: number) => {
    if (closed) return
    closed = true
    request?.abort()
    closeSource()
    receiveValue(null)
    setError(message)
    if (status === 401) expireSession()
    else if (status === 403 || status === 404) refresh()
  }
  const disconnect = () => {
    if (closed || completed) return
    request?.abort()
    closeSource()
    setError(feedbackDisconnected)
  }
  const connect = () => {
    if (closed || completed || source) return
    if (navigator.onLine === false) {
      setError(feedbackDisconnected)
      return
    }
    const opened = new EventSource(`/api/v1/jobs/${jobId}/events`)
    source = opened
    opened.addEventListener('snapshot', (event) => {
      if (!active() || source !== opened || closed || completed) return
      try {
        receive(JSON.parse((event as MessageEvent).data) as JobFeedback)
      } catch {
        disconnect()
      }
    })
    opened.addEventListener('unavailable', (event) => {
      if (!active() || source !== opened || closed || completed) return
      try {
        const failure = JSON.parse((event as MessageEvent).data) as { status: number }
        stop(
          failure.status === 401 ? '登录已过期，请重新登录。' : '处理状态已不可访问，请重新加载。',
          failure.status,
        )
      } catch {
        disconnect()
      }
    })
    opened.onopen = () => {
      if (active() && source === opened && !closed && !completed) setError('')
    }
    // Explicitly close to suppress EventSource's built-in automatic reconnect.
    opened.onerror = () => {
      if (active() && source === opened) disconnect()
    }
  }
  const recover = async () => {
    if (closed || completed || recovering || source || navigator.onLine === false) return
    if (Date.now() < retryAt) return
    recovering = true
    const controller = new AbortController()
    request = controller
    try {
      const incoming = await api<JobFeedback>(`/jobs/${jobId}/feedback`, {
        signal: controller.signal,
      })
      if (closed || controller.signal.aborted) return
      retryAt = 0
      receive(incoming)
      if (!terminalJob(incoming.state)) connect()
    } catch (failure) {
      if (closed || controller.signal.aborted || isCancelled(failure)) return
      if (failure instanceof ApiError && [401, 403, 404].includes(failure.status)) {
        stop(failure.message, failure.status)
        return
      }
      retryAt = failure instanceof ApiError ? failure.retryAt : 0
      setError(retryAt ? (failure as ApiError).message : feedbackDisconnected)
    } finally {
      if (request === controller) request = undefined
      recovering = false
    }
  }
  const online = () => void recover()
  window.addEventListener('online', online)
  window.addEventListener('offline', disconnect)
  connect()
  return {
    recover,
    dispose: () => {
      window.removeEventListener('online', online)
      window.removeEventListener('offline', disconnect)
      closed = true
      request?.abort()
      closeSource()
    },
  }
}

type FeedbackListener = {
  attempt: number
  fence: number
  receive: (value: JobFeedback | null) => void
  error: (message: string) => void
  refresh: (feedback?: JobFeedback) => void
}
type FeedbackConnection = {
  attempt: number
  fence: number
  value: JobFeedback | null
  error: string
  listeners: Set<FeedbackListener>
  dispose?: () => void
  recover?: () => Promise<void>
}
const connections = new Map<string, FeedbackConnection>()

// Message cards and the composer share one stream and explicit recovery request.
export function subscribeJobFeedback(
  jobId: string | null,
  state: string | undefined,
  attempt: number,
  fence: number,
  receive: FeedbackListener['receive'],
  error: FeedbackListener['error'],
  refresh: FeedbackListener['refresh'],
) {
  if (!jobId) return
  const generation = epoch
  const key = `${generation}:${jobId}`
  let connection = connections.get(key)
  if (state && terminalJob(state)) {
    if (connection && attempt >= connection.attempt && fence >= connection.fence) {
      connection.dispose?.()
      connection.error = ''
      connection.listeners.forEach((item) => item.error(''))
    }
    error('')
    return
  }
  const listener = { attempt, fence, receive, error, refresh }
  const restart = !connection || attempt > connection.attempt || fence > connection.fence
  if (!connection) {
    connection = { attempt, fence, value: null, error: '', listeners: new Set() }
    connections.set(key, connection)
  }
  const shared = connection
  shared.listeners.add(listener)
  if (restart) {
    shared.dispose?.()
    shared.attempt = attempt
    shared.fence = fence
    shared.value = null
    const transport = connectJobFeedback(
      jobId,
      attempt,
      fence,
      (incoming) => {
        if (epoch !== generation) return false
        const next = incoming ? acceptFeedback(shared.value, incoming, jobId) : null
        if (next === shared.value && incoming) return false
        shared.value = next
        shared.listeners.forEach((item) => {
          if (!next || (next.attempt >= item.attempt && next.fence >= item.fence))
            item.receive(next)
        })
        return true
      },
      (message) => {
        if (epoch !== generation) return
        shared.error = message
        shared.listeners.forEach((item) => item.error(message))
      },
      (feedback) => {
        if (epoch === generation) shared.listeners.forEach((item) => item.refresh(feedback))
      },
      () => epoch === generation && shared.listeners.size > 0,
    )
    shared.dispose = transport.dispose
    shared.recover = transport.recover
  }
  if (shared.value && shared.value.attempt >= attempt && shared.value.fence >= fence)
    receive(shared.value)
  error(shared.error)
  return () => {
    shared.listeners.delete(listener)
    if (!shared.listeners.size) {
      queueMicrotask(() => {
        if (shared.listeners.size) return
        shared.dispose?.()
        if (connections.get(key) === shared) connections.delete(key)
      })
    }
  }
}

export function reconnectJobFeedback(jobId: string | null) {
  return jobId ? connections.get(`${epoch}:${jobId}`)?.recover?.() : undefined
}
