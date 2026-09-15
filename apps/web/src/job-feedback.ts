import { useEffect, useRef, useState } from 'react'
import type { Job, JobFeedback } from '@paa/api-contracts'
import { api, ApiError } from './api'

export const terminalJob = (state: string) => !['queued', 'running'].includes(state)
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
    if (incoming.updatedAt <= current.updatedAt) return current
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
  complete: '已完成',
}
export function useJobFeedback(job: Job | null, enabled: boolean, refresh: () => void) {
  const [value, setValue] = useState<JobFeedback | null>(null)
  const [error, setError] = useState('')
  const refreshRef = useRef(refresh)
  useEffect(() => {
    refreshRef.current = refresh
  }, [refresh])
  const jobId = enabled && job?.kind === 'message' ? job.id : null
  const attempt = job?.attempt ?? 0
  const fence = job?.fence ?? 0
  const state = job?.state
  useEffect(() => {
    if (!jobId || state === 'succeeded' || state === 'awaiting_input' || state === 'cancelled')
      return
    let closed = false
    let source: EventSource | undefined
    let timer: ReturnType<typeof setTimeout> | undefined
    const controller = new AbortController()
    const receive = (incoming: JobFeedback) => {
      if (closed || incoming.attempt < attempt || incoming.fence < fence) return
      setValue((current) => acceptFeedback(current, incoming, jobId))
      setError('')
      if (terminalJob(incoming.state)) {
        source?.close()
        clearTimeout(timer)
        refreshRef.current()
      }
    }
    const stop = (message: string, status?: number) => {
      closed = true
      controller.abort()
      source?.close()
      clearTimeout(timer)
      setValue(null)
      setError(message)
      if (status === 401) window.dispatchEvent(new Event('paa-session-expired'))
    }
    const poll = async () => {
      try {
        const incoming = await api<JobFeedback>(`/jobs/${jobId}/feedback`, {
          signal: controller.signal,
        })
        if (closed) return
        receive(incoming)
        if (!terminalJob(incoming.state)) timer = setTimeout(poll, 5000)
      } catch (failure) {
        if (closed) return
        if (failure instanceof ApiError && [401, 403, 404].includes(failure.status)) {
          stop(failure.message, failure.status)
          return
        }
        setError('连接中断，正在恢复处理状态…')
        timer = setTimeout(poll, 5000)
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
        const failure = JSON.parse((event as MessageEvent).data) as {
          message: string
          status: number
        }
        stop(failure.message, failure.status)
      })
      source.onopen = () => {
        if (!closed) {
          setError('')
          clearTimeout(timer)
        }
      }
      source.onerror = () => {
        if (closed) return
        setError(navigator.onLine ? '实时连接中断，正在恢复…' : '网络已断开，联网后恢复处理状态。')
        clearTimeout(timer)
        timer = setTimeout(poll, 1000)
      }
    }
    return () => {
      closed = true
      controller.abort()
      source?.close()
      clearTimeout(timer)
    }
  }, [jobId, attempt, fence, state])
  return {
    feedback: enabled ? visibleFeedback(job, value) : null,
    error: job && ['succeeded', 'awaiting_input', 'cancelled'].includes(job.state) ? '' : error,
  }
}
