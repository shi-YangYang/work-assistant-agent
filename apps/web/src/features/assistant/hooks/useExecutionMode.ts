import type { ExecutionMode, ExecutionSettings } from '@paa/api-contracts'
import { ApiError, epoch, isCancelled } from '@web/api/client'
import { executionSettingsPath, updateExecutionMode } from '../api/interactions'
import { assistantQuery } from '../api/queries'
import { useQueryResource } from '@web/hooks/useQueryResource'
import type { PersonaInteraction } from './useConversationPersona'
import { useConversationRefresh } from './useConversationRefresh'
import { identityScope } from '@web/lib/session-drafts'
import { useWorkspace } from '@web/lib/workspace'
import { useLayoutEffect, useRef, useState } from 'react'

export function useExecutionMode(interaction: PersonaInteraction) {
  const { identity } = useWorkspace()
  const generation = epoch
  const owner = identityScope(identity)
  const scope = `${owner}:${generation}`
  const resource = assistantQuery<ExecutionSettings>(executionSettingsPath, owner)!
  const settings = useQueryResource(resource)
  // Shared by all conversations. Recover once on visibility/network restoration, never poll.
  useConversationRefresh(scope, () => void resource.refresh())
  const committed = useRef<string | null>(null)
  useLayoutEffect(() => {
    committed.current = scope
    return () => {
      if (committed.current === scope) committed.current = null
    }
  }, [scope])
  const valid = () => committed.current === scope && epoch === generation
  const [error, setError] = useState<{ scope: string; value: Error | string } | null>(null)
  const selected = settings.data?.executionMode ?? 'auto'
  const acknowledged = settings.data?.fullAccessConfirmed ?? false
  async function choose(mode: ExecutionMode, fullAccessConfirmed = acknowledged) {
    const current = resource.getSnapshot().data
    if (!current || mode === current.executionMode || !interaction.acquire('mode')) return
    setError(null)
    try {
      const result = await updateExecutionMode(current, mode, fullAccessConfirmed)
      if (valid()) {
        const latest = resource.getSnapshot().data
        if (!latest || result.modeRevision >= latest.modeRevision) resource.set(result)
      }
    } catch (error) {
      if (!valid() || isCancelled(error)) return
      setError({ scope, value: error as Error })
      if (error instanceof ApiError && error.code === 'execution_settings_changed') {
        await resource.refresh()
      }
    } finally {
      interaction.release('mode')
    }
  }
  async function refresh() {
    await resource.refresh()
    if (valid() && !resource.getSnapshot().error) setError(null)
  }
  return {
    selected,
    acknowledged,
    choose,
    ready: !!settings.data,
    disabled: !!interaction.busy || !settings.data,
    saving: interaction.busy === 'mode',
    error: settings.error || (error?.scope === scope ? error.value : ''),
    refresh,
  }
}
