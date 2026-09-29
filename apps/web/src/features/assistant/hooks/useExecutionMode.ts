import type { Conversation, ExecutionMode } from '@paa/api-contracts'
import { ApiError, epoch, isCancelled } from '@web/api/client'
import { updateExecutionMode } from '../api/interactions'
import { readConversation } from '../api/requests'
import type { Composer } from '../lib/audio-capture'
import type { PersonaInteraction } from './useConversationPersona'
import { identityScope } from '@web/lib/session-drafts'
import { useWorkspace } from '@web/lib/workspace'
import { useLayoutEffect, useRef, useState } from 'react'

export function useExecutionMode(
  conversationId: string | undefined,
  conversation: Conversation | null,
  interaction: PersonaInteraction,
  onSaved: (conversation: Conversation) => void,
) {
  const { identity, drafts, setDraft } = useWorkspace()
  const generation = epoch
  const owner = `${identityScope(identity)}:${generation}`
  const scope = `${owner}:${conversationId ?? 'new'}`
  const committed = useRef<string | null>(null)
  useLayoutEffect(() => {
    committed.current = scope
    return () => {
      if (committed.current === scope) committed.current = null
    }
  }, [scope])
  const valid = () => committed.current === scope && epoch === generation
  const [saved, setSaved] = useState<{ scope: string; conversation: Conversation } | null>(null)
  const [error, setError] = useState<{ scope: string; value: Error | string } | null>(null)
  const [created, setCreated] = useState<{
    owner: string
    id: string
    mode: ExecutionMode
    acknowledged: boolean
  } | null>(null)
  const current =
    saved?.scope === scope &&
    (!conversation || saved.conversation.revision >= conversation.revision)
      ? saved.conversation
      : conversation
  const draft = drafts['composer:new'] as Composer | undefined
  const adopted = created?.owner === owner && created.id === conversationId ? created : null
  const selected = conversationId
    ? (current?.executionMode ?? adopted?.mode ?? 'auto')
    : (draft?.executionMode ?? 'auto')
  const acknowledged = conversationId
    ? (current?.fullAccessConfirmed ?? adopted?.acknowledged ?? false)
    : !!draft?.fullAccessConfirmed
  async function choose(mode: ExecutionMode, fullAccessConfirmed = acknowledged) {
    if (mode === selected || (conversationId && !current) || !interaction.acquire('mode')) return
    setError(null)
    try {
      if (!conversationId) {
        setDraft('composer:new', (previous: Composer | undefined) => ({
          ...(previous ?? { text: '', files: [], key: '' }),
          executionMode: mode,
          fullAccessConfirmed,
        }))
        return
      }
      const result = await updateExecutionMode(current!, mode, fullAccessConfirmed)
      if (!valid()) return
      setSaved({ scope, conversation: result })
      onSaved(result)
    } catch (error) {
      if (!valid() || isCancelled(error)) return
      setError({ scope, value: error as Error })
      if (error instanceof ApiError && error.status === 409 && current) {
        try {
          const latest = await readConversation(current)
          if (valid()) {
            setSaved({ scope, conversation: latest })
            onSaved(latest)
          }
        } catch {
          /* Keep the original conflict until the next reload. */
        }
      }
    } finally {
      interaction.release('mode')
    }
  }
  return {
    selected,
    acknowledged,
    choose,
    disabled: !!interaction.busy || (!!conversationId && !current),
    saving: interaction.busy === 'mode',
    error: error?.scope === scope ? error.value : '',
    adoptCreated: (id: string) => {
      if (valid()) setCreated({ owner, id, mode: selected, acknowledged })
    },
  }
}
