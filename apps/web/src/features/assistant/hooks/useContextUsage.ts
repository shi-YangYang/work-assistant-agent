import type { ContextUsage, Job, JobFeedback } from '@paa/api-contracts'
import { ApiError, epoch, isCancelled } from '@web/api/client'
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

export function useContextUsage(conversationId: string | undefined, latestJob: Job | null) {
  const { identity } = useWorkspace()
  const scope = `${identityScope(identity)}:${epoch}:${conversationId ?? 'new'}`
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const activeScope = useRef(scope)
  const latestId = latestJob?.id ?? null
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
        const current = previous?.scope === scope && previous.jobId === job.id ? previous : null
        if (
          current &&
          (attempt < current.attempt || (attempt === current.attempt && fence < current.fence))
        )
          return previous
        const reset = !current || attempt > current.attempt || fence > current.fence
        const next = usage
          ? newerContext(reset ? null : current.usage, usage)
          : reset
            ? null
            : current.usage
        if (current && next === current.usage && !reset) return previous
        return { scope, jobId: job.id, attempt, fence, usage: next, unavailable: false }
      })
    },
    [scope, latestId],
  )

  useEffect(() => {
    if (!conversationId) return
    let active = true
    let controller: AbortController | undefined
    const restore = async () => {
      controller?.abort()
      const request = new AbortController()
      controller = request
      const receivedAtStart = receivedUpdates.current
      try {
        const { contextUsage } = await readConversationContext(conversationId, request.signal)
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
          if (latestId && contextUsage.jobId !== latestId) return previous
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
      }
    }
    void restore()
    window.addEventListener('online', restore)
    return () => {
      active = false
      controller?.abort()
      window.removeEventListener('online', restore)
    }
  }, [scope, conversationId, latestId])

  const visible =
    snapshot?.scope === scope && (!latestId || snapshot.jobId === latestId) ? snapshot : null
  const usage = visible?.usage ?? null
  const current =
    usage &&
    latestJob &&
    (usage.attempt < (latestJob.attempt ?? 0) ||
      (usage.attempt === (latestJob.attempt ?? 0) && usage.fence < (latestJob.fence ?? 0)))
      ? null
      : usage
  return { usage: current, unavailable: visible?.unavailable ?? false, receive }
}
