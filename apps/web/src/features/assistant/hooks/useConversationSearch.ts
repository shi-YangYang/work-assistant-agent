import type { Conversation, Page } from '@paa/api-contracts'
import { epoch, isCancelled } from '@web/api/client'
import { readMoreConversations } from '@web/features/assistant/api/requests'
import { useWorkspace } from '@web/lib/workspace'
import { identityScope } from '@web/lib/session-drafts'
import { useCallback, useEffect, useRef, useState } from 'react'

export function useConversationSearch(open: boolean) {
  const { identity } = useWorkspace()
  const [search, setSearch] = useState('')
  const [revision, setRevision] = useState(0)
  const key = `${identityScope(identity)}:${epoch}:${open}:${search}:${revision}`
  const current = useRef(key)
  current.current = key
  const flight = useRef<{ key: string; controller: AbortController } | null>(null)
  const [state, setState] = useState<{
    key: string
    data: Page<Conversation> | null
    error: Error | string
    loading: boolean
  }>({ key, data: null, error: '', loading: false })
  const refresh = useCallback(() => setRevision((value) => value + 1), [])
  const data = state.key === key ? state.data : null
  const load = async (cursor?: string | null) => {
    if (!open || (flight.current?.key === key && !flight.current.controller.signal.aborted)) return
    const controller = new AbortController()
    flight.current = { key, controller }
    const valid = () => current.current === key && !controller.signal.aborted
    setState((previous) => ({
      key,
      data: previous.key === key ? previous.data : null,
      error: '',
      loading: true,
    }))
    try {
      const result = await readMoreConversations(search, cursor, controller.signal)
      if (!valid()) return
      setState((previous) => ({
        key,
        data: {
          ...result,
          items:
            cursor && previous.key === key
              ? [...(previous.data?.items ?? []), ...result.items].filter(
                  (item, index, all) => all.findIndex((row) => row.id === item.id) === index,
                )
              : result.items,
        },
        error: '',
        loading: false,
      }))
    } catch (error) {
      if (valid() && !isCancelled(error))
        setState((previous) => ({ ...previous, loading: false, error: error as Error }))
    } finally {
      if (flight.current?.controller === controller) flight.current = null
    }
  }
  useEffect(() => {
    void load()
    return () => {
      if (flight.current?.key === key) {
        flight.current.controller.abort()
        flight.current = null
      }
    }
    // A request belongs to this complete scope; changing it invalidates all pages.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return {
    search,
    setSearch,
    data,
    refresh,
    error: state.key === key ? state.error : '',
    loading: state.key === key && state.loading,
    loadMore: () => (data?.nextCursor ? load(data.nextCursor) : Promise.resolve()),
  }
}
