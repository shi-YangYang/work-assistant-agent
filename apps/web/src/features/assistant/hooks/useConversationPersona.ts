import type { Conversation, PersonaId } from '@paa/api-contracts'
import { ApiError, epoch, isCancelled } from '@web/api/client'
import { readConversation, updateConversationPersona } from '@web/features/assistant/api/requests'
import type { Composer } from '@web/features/assistant/lib/audio-capture'
import { identityScope } from '@web/lib/session-drafts'
import { useWorkspace } from '@web/lib/workspace'
import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react'

type Operation = 'persona' | 'message' | 'preview'
export type PersonaInteraction = {
  busy: Operation | null
  acquire: (operation: Operation) => boolean
  release: (operation: Operation) => void
}
type Session = { scope: string }
type Selection = {
  session: Session
  scope: string
  confirmed?: Conversation
  created?: { id: string; personaId: PersonaId }
  pending?: PersonaId
  error?: Error | string
}

export function useConversationPersona(
  conversationId: string | undefined,
  conversation: Conversation | null,
  onSaved: () => void,
) {
  const { identity, drafts, setDraft } = useWorkspace()
  const ownerScope = `${identityScope(identity)}:${epoch}`
  const scope = `${ownerScope}:${conversationId ?? 'new'}`
  const session = useMemo(() => ({ scope }), [scope])
  const committed = useRef<{ session: Session; operation: Operation | null } | null>(null)
  const sessionEpoch = epoch
  useLayoutEffect(() => {
    const current = { session, operation: null }
    committed.current = current
    return () => {
      if (committed.current === current) committed.current = null
    }
  }, [session])
  const valid = () => committed.current?.session === session && epoch === sessionEpoch
  const [selection, setSelection] = useState<Selection | null>(null)
  const [operation, setOperation] = useState<{ session: Session; value: Operation | null } | null>(
    null,
  )
  const current = selection?.session === session ? selection : null
  const confirmed =
    current?.confirmed && (!conversation || current.confirmed.revision >= conversation.revision)
      ? current.confirmed
      : conversation
  const draft = drafts['composer:new'] as Composer | undefined
  const selected =
    current?.pending ??
    (conversationId
      ? (confirmed?.personaId ??
        (selection?.scope === `${ownerScope}:new` && selection.created?.id === conversationId
          ? selection.created.personaId
          : 'professional'))
      : (draft?.personaId ?? 'dabao'))
  const acquire = useCallback(
    (value: Operation) => {
      const current = committed.current
      if (current?.session !== session || current.operation || epoch !== sessionEpoch) return false
      current.operation = value
      setOperation({ session, value })
      return true
    },
    [session, sessionEpoch],
  )
  const release = useCallback(
    (value: Operation) => {
      const current = committed.current
      if (current?.session !== session || current.operation !== value) return
      current.operation = null
      setOperation({ session, value: null })
    },
    [session],
  )
  const composer = drafts[`composer:${conversationId ?? 'new'}`] as Composer | undefined
  const submitting = !!composer?.sending || !!composer?.uploading
  async function choose(personaId: PersonaId) {
    if (
      submitting ||
      personaId === selected ||
      (conversationId && !confirmed) ||
      !acquire('persona')
    )
      return
    if (!conversationId) {
      setDraft('composer:new', (previous: Composer | undefined) => ({
        ...(previous ?? { text: '', files: [], key: '' }),
        personaId,
      }))
      release('persona')
      return
    }
    const previous = confirmed!
    setSelection({ session, scope, confirmed: previous, pending: personaId })
    try {
      const saved = await updateConversationPersona(previous, {
        personaId,
        expectedRevision: previous.revision,
      })
      if (!valid()) return
      setSelection({ session, scope, confirmed: saved })
      onSaved()
    } catch (error) {
      if (!valid() || isCancelled(error)) return
      setSelection({ session, scope, confirmed: previous, error: error as Error })
      if (error instanceof ApiError && error.status === 409) {
        try {
          const latest = await readConversation(previous)
          if (valid()) {
            setSelection({ session, scope, confirmed: latest, error })
            onSaved()
          }
        } catch {
          // Keep the confirmed choice and original conflict visible; a later retry rechecks it.
        }
      }
    } finally {
      release('persona')
    }
  }
  return {
    selected,
    choose,
    error: current?.error ?? '',
    disabled: (!!conversationId && !confirmed) || submitting,
    interaction: {
      busy: operation?.session === session ? operation.value : null,
      acquire,
      release,
    } satisfies PersonaInteraction,
    adoptCreated: (id: string, personaId: PersonaId) => {
      if (valid()) setSelection({ session, scope, created: { id, personaId } })
    },
  }
}
