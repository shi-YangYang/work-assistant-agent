import type { ReasoningSettings } from '@paa/api-contracts'
import { write } from '@web/api/client'

export const reasoningSettingsPath = '/assistant/reasoning-settings'
export function updateReasoningEffort(current: ReasoningSettings, effort: string) {
  return write<ReasoningSettings>(
    reasoningSettingsPath,
    {
      effort,
      preferenceRevision: current.preferenceRevision,
      configVersion: current.configVersion,
    },
    'PATCH',
  )
}
