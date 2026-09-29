import type { ContextUsage, Job, JobFeedback } from '@paa/api-contracts'
import { ApiError, epoch, isCancelled } from '@web/api/client'
import { assistantQuery } from '../api/queries'
import { readConversationContext } from '@web/features/assistant/api/requests'
import { identityScope } from '@web/lib/session-drafts'
import { useWorkspace } from '@web/lib/workspace'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

export function newerContext(current: ContextUsage | null, incoming: ContextUsage) {
  if (!current || current.jobId !== incoming.jobId) return incoming
  for (const field of ['attempt', 'fence', 'seq'] as const) {
    if (incoming[field] < current[field]) return current
    if (incoming[field] > current[field]) return incoming
  }
  return incoming.updatedAt > current.updatedAt ? incoming : current
}

type Snapshot = {
  scope: string
  jobId: string | null
  attempt: number
  fence: number
  usage: ContextUsage | null
  unavailable: boolean
}

export function useContextUsage(
  conversationId: string | undefined,
  latestJob: Job | null,
  managed = false,
) {
  const { identity } = useWorkspace()
  const scope = `${identityScope(identity)}:${epoch}:${conversationId ?? 'new'}`
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [restoredScope, setRestoredScope] = useState<string | null>(null)
  const activeScope = useRef(scope)
  const latestId = latestJob?.id ?? null
  const latestRef = useRef(latestId)
  useLayoutEffect(() => {
    latestRef.current = latestId
  }, [latestId])
  const resource = assistantQuery<{ contextUsage: ContextUsage | null }>(
    conversationId ? `/conversations/${conversationId}/context-usage` : null,
    identityScope(identity),
    (signal) => readConversationContext(conversationId!, signal),
  )
  const receivedUpdates = useRef(0)
  useLayoutEffect(() => {
    activeScope.current = scope
    return () => {
      activeScope.current = ''
    }
  }, [scope])
  const receive = useCallback(
    (job: Job, feedback: JobFeedback | null) => {
      if (activeScope.current !== scope || job.id !== latestId) return
      receivedUpdates.current++
      const attempt = feedback?.attempt ?? job.attempt ?? 0
      const fence = feedback?.fence ?? job.fence ?? 0
      const candidate = feedback?.contextUsage ?? job.contextUsage ?? null
      const usage =
        candidate &&
        candidate.jobId === job.id &&
        candidate.attempt >= attempt &&
        candidate.fence >= fence
          ? candidate
          : null
      setSnapshot((previous) => {
        const scoped = previous?.scope === scope ? previous : null
        const current = scoped?.jobId === job.id ? scoped : null
        if (
          current &&
          (attempt < current.attempt || (attempt === current.attempt && fence < current.fence))
        )
          return previous
        const reset = !current || attempt > current.attempt || fence > current.fence
        const next = usage
          ? newerContext(reset ? null : current.usage, usage)
          : reset
            ? scoped?.usage?.jobId !== job.id && scoped?.usage?.state === 'ready'
              ? scoped.usage
              : null
            : current.usage
        if (current && next === current.usage && !reset) return previous
        return { scope, jobId: job.id, attempt, fence, usage: next, unavailable: false }
      })
    },
    [scope, latestId],
  )

  useEffect(() => {
    if (!conversationId || !resource) return
    let active = true
    let controller: AbortController | undefined
    const restore = async () => {
      const latestId = latestRef.current
      controller?.abort()
      const request = new AbortController()
      controller = request
      const receivedAtStart = receivedUpdates.current
      try {
        const { contextUsage } = await resource.get(request.signal)
        if (!active || request.signal.aborted) return
        setSnapshot((previous) => {
          const current = previous?.scope === scope ? previous : null
          if (!contextUsage)
            return current?.usage && receivedUpdates.current !== receivedAtStart
              ? previous
              : {
                  scope,
                  jobId: latestId,
                  attempt: 0,
                  fence: 0,
                  usage: null,
                  unavailable: false,
                }
          // A slow restore cannot replace a newer message or a restarted attempt.
          if (latestId && contextUsage.jobId !== latestId) {
            // The endpoint returns the last estimate, even when a new job has not estimated yet.
            // Keep it until that job produces its own snapshot, without restoring old activity.
            if (current?.usage || contextUsage.state !== 'ready') return previous
          }
          if (
            current &&
            current.jobId === contextUsage.jobId &&
            (contextUsage.attempt < current.attempt ||
              (contextUsage.attempt === current.attempt && contextUsage.fence < current.fence))
          )
            return previous
          const next = newerContext(current?.usage ?? null, contextUsage)
          if (current && next === current.usage && !current.unavailable) return previous
          return {
            scope,
            jobId: next.jobId,
            attempt: next.attempt,
            fence: next.fence,
            usage: next,
            unavailable: false,
          }
        })
      } catch (error) {
        if (!active || isCancelled(error)) return
        setSnapshot((previous) =>
          previous?.scope === scope &&
          previous.usage &&
          !(error instanceof ApiError && [401, 403, 404].includes(error.status))
            ? previous
            : {
                scope,
                jobId: latestId,
                attempt: 0,
                fence: 0,
                usage: null,
                unavailable: true,
              },
        )
      } finally {
        if (active && !request.signal.aborted) setRestoredScope(scope)
      }
    }
    const unsubscribe = resource.subscribe(() => {
      if (!resource.getSnapshot().loading) void restore()
    })
    const refresh = () => void resource.refresh()
    void restore()
    if (!managed) window.addEventListener('online', refresh)
    return () => {
      active = false
      controller?.abort()
      unsubscribe()
      window.removeEventListener('online', refresh)
    }
  }, [scope, conversationId, resource, managed])

  const visible = snapshot?.scope === scope ? snapshot : null
  const usage = visible?.usage ?? null
  const current =
    usage &&
    latestJob &&
    (usage.jobId !== latestJob.id
      ? usage.state !== 'ready'
      : usage.attempt < (latestJob.attempt ?? 0) ||
        (usage.attempt === (latestJob.attempt ?? 0) && usage.fence < (latestJob.fence ?? 0)))
      ? null
      : usage
  return {
    usage: current,
    loading: !!conversationId && !current && !visible?.unavailable && restoredScope !== scope,
    unavailable: visible?.unavailable ?? false,
    receive,
    refresh: resource?.refresh ?? (() => Promise.resolve()),
  }
}
