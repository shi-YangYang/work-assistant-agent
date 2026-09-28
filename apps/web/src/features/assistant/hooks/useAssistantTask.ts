import type { Job, WorkMessage } from '@paa/api-contracts'
import { epoch, isCancelled } from '@web/api/client'
import { readActiveAssistantJob } from '@web/features/assistant/api/requests'
import { cancelJob } from '@web/features/jobs/api/requests'
import { useJobFeedback } from '@web/hooks/useJobFeedback'
import { identityScope } from '@web/lib/session-drafts'
import { useWorkspace } from '@web/lib/workspace'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

const activeJob = (job: Job | null) => !!job && ['queued', 'running'].includes(job.state)
const activityKey = (owner: string, id: string) => `paa-assistant-task:${owner}:${id}`
function announce(owner: string, id: string) {
  try {
    localStorage.setItem(activityKey(owner, id), crypto.randomUUID())
  } catch {
    // Focus/online recovery and the server's conversation guard remain available.
  }
}

type Snapshot = {
  scope: string
  job: Job | null
  checking: boolean
  cancelling: boolean
  error: Error | string
}

export function useAssistantTask(conversationId: string | undefined, messages: WorkMessage[]) {
  const { identity } = useWorkspace()
  const owner = identityScope(identity)
  const generation = epoch
  const scope = `${owner}:${generation}:${conversationId ?? 'new'}`
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const committed = useRef<{
    scope: string
    conversationId?: string
    value: Snapshot
    revision: number
    controller?: AbortController
    retrying: boolean
  } | null>(null)
  useLayoutEffect(() => {
    const current: NonNullable<typeof committed.current> = {
      scope,
      conversationId,
      value: { scope, job: null, checking: !!conversationId, cancelling: false, error: '' },
      revision: 0,
      retrying: false,
    }
    committed.current = current
    return () => {
      if (committed.current === current) committed.current = null
      current.controller?.abort()
    }
  }, [scope, conversationId])
  const valid = useCallback(
    () => (committed.current?.scope === scope && epoch === generation ? committed.current : null),
    [scope, generation],
  )
  const update = useCallback(
    (patch: Partial<Snapshot>) => {
      const current = valid()
      if (!current) return
      current.value = { ...current.value, ...patch }
      setSnapshot(current.value)
    },
    [valid],
  )
  const refresh = useCallback(async () => {
    const current = valid()
    if (!current?.conversationId) return
    current.controller?.abort()
    const controller = new AbortController()
    current.controller = controller
    const revision = ++current.revision
    update({ checking: true })
    try {
      const { job } = await readActiveAssistantJob(current.conversationId, controller.signal)
      if (valid() !== current || controller.signal.aborted || current.revision !== revision) return
      // Keep the last terminal snapshot until history catches up, but never a stale active one.
      update({
        job: job ?? (activeJob(current.value.job) ? null : current.value.job),
        checking: false,
        error: '',
      })
    } catch (error) {
      if (valid() !== current || controller.signal.aborted || isCancelled(error)) return
      update({ error: error instanceof Error ? error : '处理状态暂不可用，请重试。' })
    }
  }, [valid, update])
  const historyActivity = messages
    .filter((message) => !message.businessUnavailable && activeJob(message.job))
    .map((message) => `${message.job!.id}:${message.job!.attempt}:${message.job!.fence}`)
    .join('|')
  useEffect(() => {
    void refresh()
    const recover = () => {
      if (!document.hidden) void refresh()
    }
    const changed = (event: StorageEvent) => {
      if (conversationId && event.key === activityKey(owner, conversationId)) void refresh()
    }
    window.addEventListener('online', recover)
    window.addEventListener('focus', recover)
    window.addEventListener('storage', changed)
    document.addEventListener('visibilitychange', recover)
    return () => {
      window.removeEventListener('online', recover)
      window.removeEventListener('focus', recover)
      window.removeEventListener('storage', changed)
      document.removeEventListener('visibilitychange', recover)
    }
  }, [refresh, owner, conversationId, historyActivity])
  const current = snapshot?.scope === scope ? snapshot : null
  const job = current?.job ?? null
  const live = useJobFeedback(job, true, refresh)
  useEffect(() => {
    const state = valid()
    const feedback = live.feedback
    if (!state?.value.job || !feedback || feedback.jobId !== state.value.job.id) return
    if (
      feedback.attempt < (state.value.job.attempt ?? 0) ||
      feedback.fence < (state.value.job.fence ?? 0)
    )
      return
    if (
      state.value.job.updatedAt === feedback.updatedAt &&
      state.value.job.state === feedback.state &&
      state.value.job.attempt === feedback.attempt &&
      state.value.job.fence === feedback.fence
    )
      return
    const next = { ...state.value.job, ...feedback, id: feedback.jobId }
    update({ job: next })
  }, [live.feedback, update, valid])
  const accepted = (sent: { conversationId: string; messageId: string; jobId: string }) => {
    const state = valid()
    if (!state) return
    state.conversationId = sent.conversationId
    state.revision++
    update({
      job: {
        id: sent.jobId,
        targetId: sent.messageId,
        kind: 'message',
        state: 'queued',
        phase: 'assistant',
        stage: 'queued',
        attempt: 0,
        fence: 0,
        error: '',
        updatedAt: new Date().toISOString(),
      },
      checking: true,
      error: '',
    })
    announce(owner, sent.conversationId)
    void refresh()
  }
  const canSubmit = () => {
    const state = valid()
    return (
      !!state &&
      !state.retrying &&
      !state.value.checking &&
      !state.value.cancelling &&
      !activeJob(state.value.job)
    )
  }
  const beginRetry = () => {
    if (!canSubmit()) return false
    valid()!.retrying = true
    update({ checking: true, error: '' })
    return true
  }
  const finishRetry = (next: Job | null) => {
    const state = valid()
    if (!state) return
    state.retrying = false
    if (next) update({ job: next })
    if (state.conversationId) announce(owner, state.conversationId)
    void refresh()
  }
  const interrupt = async () => {
    const state = valid()
    const target = state?.value.job
    if (!state || !target || !activeJob(target) || state.value.cancelling || state.retrying) return
    update({ cancelling: true, error: '' })
    try {
      const result = await cancelJob(target)
      if (valid() !== state) return
      state.revision++
      update({ job: result })
      if (state.conversationId) announce(owner, state.conversationId)
      await refresh()
    } catch (error) {
      if (valid() !== state || isCancelled(error)) return
      update({ error: error instanceof Error ? error : '中断未确认，请重试。' })
      // A version conflict must refresh the active attempt before another interruption.
      if (error instanceof Error && 'status' in error && error.status === 409) await refresh()
    } finally {
      if (valid() === state) update({ cancelling: false })
    }
  }
  return {
    job,
    feedback: live.feedback,
    running: activeJob(job),
    blocked: !current ? !!conversationId : current.checking || current.cancelling || activeJob(job),
    checking: current?.checking ?? !!conversationId,
    cancelling: current?.cancelling ?? false,
    error: current?.error || live.error,
    accepted,
    canSubmit,
    beginRetry,
    finishRetry,
    interrupt,
    refresh,
  }
}
