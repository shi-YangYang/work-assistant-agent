import type { Job, JobFeedback, WorkMessage } from '@paa/api-contracts'
import { epoch, isCancelled } from '@web/api/client'
import { assistantQuery } from '../api/queries'
import { readActiveAssistantJob } from '@web/features/assistant/api/requests'
import { cancelJob } from '@web/features/jobs/api/requests'
import { useJobFeedback } from '@web/hooks/useJobFeedback'
import { identityScope } from '@web/lib/session-drafts'
import { useWorkspace } from '@web/lib/workspace'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

const activeJob = (job: Job | null) => !!job && ['queued', 'running'].includes(job.state)
const activityKey = (owner: string, id: string) => `paa-assistant-task:${owner}:${id}`
function announce(owner: string, id: string) {
  try {
    localStorage.setItem(activityKey(owner, id), crypto.randomUUID())
  } catch {
    // Visibility/online recovery and the server's conversation guard remain available.
  }
}

type Snapshot = {
  scope: string
  job: Job | null
  checking: boolean
  cancelling: boolean
  error: Error | string
}

export function useAssistantTask(
  conversationId: string | undefined,
  _messages: WorkMessage[],
  onSync?: (feedback?: JobFeedback) => void,
  managed = false,
) {
  const { identity } = useWorkspace()
  const owner = identityScope(identity)
  const generation = epoch
  const scope = `${owner}:${generation}:${conversationId ?? 'new'}`
  const resource = assistantQuery<{ job: Job | null }>(
    conversationId ? `/conversations/${conversationId}/active-job` : null,
    owner,
    (signal) => readActiveAssistantJob(conversationId!, signal),
  )
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const syncRef = useRef(onSync)
  useEffect(() => {
    syncRef.current = onSync
  }, [onSync])
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
  const restore = useCallback(
    async (fresh = false) => {
      const current = valid()
      if (!current?.conversationId) return
      current.controller?.abort()
      const controller = new AbortController()
      current.controller = controller
      const revision = ++current.revision
      current.value = { ...current.value, checking: true }
      if (!resource) return
      if (fresh) await resource.refresh()
      await resource.get(controller.signal).then(
        ({ job }) => {
          if (valid() !== current || controller.signal.aborted || current.revision !== revision)
            return
          // Keep the last terminal snapshot until history catches up, but never a stale active one.
          update({
            job: job ?? (activeJob(current.value.job) ? null : current.value.job),
            checking: false,
            error: '',
          })
        },
        (error: unknown) => {
          if (
            valid() !== current ||
            controller.signal.aborted ||
            current.revision !== revision ||
            isCancelled(error)
          )
            return
          update({
            checking: true,
            error: error instanceof Error ? error : '处理状态暂不可用，请重试。',
          })
        },
      )
    },
    [valid, update, resource],
  )
  const refresh = useCallback(async () => {
    if (!valid()?.conversationId) return
    update({ checking: true })
    await restore(true)
  }, [restore, update, valid])
  useEffect(() => {
    const unsubscribe = resource?.subscribe(() => {})
    void restore()
    const recover = () => {
      if (!document.hidden) void refresh()
    }
    const changed = (event: StorageEvent) => {
      if (conversationId && event.key === activityKey(owner, conversationId)) {
        void refresh()
        syncRef.current?.()
      }
    }
    if (!managed) window.addEventListener('online', recover)
    window.addEventListener('storage', changed)
    if (!managed) document.addEventListener('visibilitychange', recover)
    return () => {
      unsubscribe?.()
      window.removeEventListener('online', recover)
      window.removeEventListener('storage', changed)
      document.removeEventListener('visibilitychange', recover)
    }
  }, [restore, refresh, owner, conversationId, managed, resource])
  const current = snapshot?.scope === scope ? snapshot : null
  const sourceJob = current?.job ?? null
  const live = useJobFeedback(sourceJob, true, (feedback) => {
    if (!feedback || !['queued', 'running'].includes(feedback.state)) void refresh()
    syncRef.current?.(feedback)
  })
  const job = useMemo(
    () =>
      sourceJob && live.feedback
        ? { ...sourceJob, ...live.feedback, id: live.feedback.jobId }
        : sourceJob,
    [sourceJob, live.feedback],
  )
  useLayoutEffect(() => {
    const state = valid()
    if (!state || !job || state.value.job?.id !== job.id) return
    // Render directly from feedback; event guards use the same committed job.
    state.value = { ...state.value, job }
  }, [job, valid])
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
    assistantQuery<{ job: Job | null }>(
      `/conversations/${sent.conversationId}/active-job`,
      owner,
    )?.set({ job: valid()!.value.job })
    announce(owner, sent.conversationId)
    update({ checking: false })
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
    if (next) {
      resource?.set({ job: next })
      update({ job: next })
    }
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
      resource?.set({ job: result })
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
    synchronize: async () => {
      await Promise.all([refresh(), live.reconnect()])
    },
    refresh: async () => {
      await Promise.all([refresh(), live.reconnect()])
      syncRef.current?.()
    },
  }
}
