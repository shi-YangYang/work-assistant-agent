import { epoch } from '@web/api/client'
import { useWorkspace } from '@web/lib/workspace'
import { identityScope } from '@web/lib/session-drafts'
import { useLayoutEffect, useRef, useState } from 'react'

function initialSubmission(scope: string, active: boolean) {
  return { scope, active, session: {}, busy: false }
}

/** A response owns only the draft snapshot and mounted editing session that submitted it. */
export function useDraftSubmission(key: string, active = true) {
  const { identity, drafts, setDraft } = useWorkspace()
  const scope = `${identityScope(identity)}:${epoch}:${key}`
  const [local, setLocal] = useState(() => initialSubmission(scope, active))
  if (local.scope !== scope || local.active !== active) setLocal(initialSubmission(scope, active))
  const { session, busy } = local
  const current = useRef<{ token: object; request: object | null } | null>(null)
  const snapshot = drafts[key]
  const latestDraft = useRef(snapshot)
  const setBusy = (busy: boolean) => setLocal({ ...local, busy })
  useLayoutEffect(() => {
    latestDraft.current = snapshot
  }, [snapshot])
  useLayoutEffect(() => {
    const committed = { token: session, request: null }
    current.current = committed
    return () => {
      if (current.current === committed) current.current = null
    }
  }, [session])
  async function submit<T>(
    request: () => Promise<T>,
    onSaved: (result: T) => void,
    onError: (error: unknown) => void,
  ) {
    const committed = current.current
    if (!active || !committed || committed.token !== session || committed.request) return
    const submission = {}
    committed.request = submission
    const sessionEpoch = epoch
    const valid = () =>
      current.current === committed && committed.request === submission && epoch === sessionEpoch
    setBusy(true)
    try {
      const result = await request()
      if (!valid()) return
      const unchanged = latestDraft.current === snapshot
      // Functional updates run against the latest vault, not the captured React render.
      setDraft(key, (latest: unknown) => (latest === snapshot ? undefined : latest))
      if (unchanged) onSaved(result)
    } catch (error) {
      if (valid()) onError(error)
    } finally {
      if (valid()) {
        committed.request = null
        setBusy(false)
      }
    }
  }
  return { busy: active && busy, submit }
}
