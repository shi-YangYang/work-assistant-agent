import { validateParameters, type JsonValue } from '@paa/model-config'
import type { ModelPresets } from './summary-contracts'
export function selectedParameters(
  models: ModelPresets[],
  model: string,
): Record<string, JsonValue> {
  const entry = models.find((item) => item.model === model)
  const preset = entry?.presets.find((item) => item.id === entry.selectedPresetId)
  if (!preset) return {}
  const value = preset.mode === 'simple' ? { reasoning_effort: preset.value } : preset.parameters
  validateParameters(value)
  return value
}
