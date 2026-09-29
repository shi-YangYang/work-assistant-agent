import type { AssistantInteraction } from '@paa/api-contracts'
import { epoch, isCancelled, ApiError } from '@web/api/client'
import { mergeInteractions } from '../utils/interactions'
import { useResource } from '@web/hooks/useResource'
import { useWorkspace } from '@web/lib/workspace'
import { identityScope } from '@web/lib/session-drafts'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import {
  answerInteraction,
  cancelInteraction,
  conversationInteractionsPath,
  type InteractionAnswer,
  type TaskContinuation,
} from '../api/interactions'

export function useAssistantInteraction(
  conversationId: string | undefined,
  incoming: AssistantInteraction[],
  onContinue: (value?: TaskContinuation) => void,
) {
  const { identity, drafts, setDraft } = useWorkspace()
  const generation = epoch
  const scope = `${identityScope(identity)}:${generation}:${conversationId ?? 'new'}`
  const resource = useResource<{ items: AssistantInteraction[] }>(
    conversationInteractionsPath(conversationId),
  )
  const committed = useRef<object | null>(null)
  useLayoutEffect(() => {
    const current = {}
    committed.current = current
    return () => {
      if (committed.current === current) committed.current = null
    }
  }, [scope])
  const [local, setLocal] = useState<{
    scope: string
    items: AssistantInteraction[]
    busy?: string
    error?: Error | string
  } | null>(null)
  const current = local?.scope === scope ? local : null
  const lock = useRef<object | null>(null)
  const pending = useRef<{ scope: string; payload: string; key: string } | null>(null)
  const unavailable =
    resource.error instanceof ApiError &&
    ([401, 403, 404].includes(resource.error.status) ||
      ['business_access_changed', 'source_changed'].includes(resource.error.code))
  const items = useMemo(
    () => (unavailable ? [] : mergeInteractions(current?.items, incoming, resource.data?.items)),
    [unavailable, incoming, resource.data, current?.items],
  )
  const finishedDrafts = Object.keys(drafts).filter((key) =>
    items.some((item) => item.state !== 'waiting' && key.startsWith(`question:${item.id}:`)),
  )
  const finishedKeys = finishedDrafts.join('|')
  useEffect(() => {
    if (finishedKeys) for (const key of finishedKeys.split('|')) setDraft(key, undefined)
  }, [finishedKeys, setDraft])
  const waiting = [...items].reverse().find((item) => item.state === 'waiting')
  const refresh = resource.refresh
  const respond = useCallback(
    async (item: AssistantInteraction, answers?: InteractionAnswer[]) => {
      const session = committed.current
      if (!session || lock.current === session || epoch !== generation) return
      lock.current = session
      const valid = () => committed.current === session && epoch === generation
      const payload = JSON.stringify([item.id, item.revision, answers ?? null])
      if (pending.current?.scope !== scope || pending.current.payload !== payload)
        pending.current = { scope, payload, key: crypto.randomUUID() }
      const key = pending.current.key
      setLocal((previous) => ({
        scope,
        items: previous?.scope === scope ? previous.items : [],
        busy: item.id,
      }))
      try {
        const result = answers
          ? await answerInteraction(item, answers, key)
          : await cancelInteraction(item, key)
        if (!valid()) return
        pending.current = null
        setDraft(`question:${item.id}:${item.revision}`, undefined)
        setLocal((previous) => ({
          scope,
          items: [
            ...(previous?.scope === scope
              ? previous.items.filter((row) => row.id !== item.id)
              : []),
            result.interaction,
          ],
        }))
        refresh()
        onContinue(result.continuation)
      } catch (error) {
        if (!valid() || isCancelled(error)) return
        setLocal((previous) => ({
          scope,
          items: previous?.scope === scope ? previous.items : [],
          error: error as Error,
        }))
        if (error instanceof ApiError && [403, 404, 409].includes(error.status)) refresh()
      } finally {
        if (lock.current === session) lock.current = null
      }
    },
    [generation, scope, refresh, onContinue, setDraft],
  )
  return {
    items,
    unavailable,
    waiting,
    busy: current?.busy,
    error: current?.error || resource.error,
    respond,
    refresh,
  }
}
