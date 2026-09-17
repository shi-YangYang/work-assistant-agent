import type { JsonValue } from '@paa/model-config'
import { ID_PATTERN } from './contracts'
export type { JsonValue } from '@paa/model-config'
export type ReasoningPreset = { id: string; name: string } & (
  { mode: 'simple'; value: string } | { mode: 'advanced'; parameters: Record<string, JsonValue> }
)
export type ModelPresets = {
  model: string
  selectedPresetId: string | null
  presets: ReasoningPreset[]
}
export type ServiceProfile = {
  id: string
  revision: string
  name: string
  baseUrl: string
  model: string
  stream: boolean
  models: ModelPresets[]
  hasKey: boolean
}
export type ServiceDraft = Omit<ServiceProfile, 'hasKey' | 'revision'> & { apiKey: string }
export type ServiceList = {
  profiles: Pick<ServiceProfile, 'id' | 'name' | 'baseUrl' | 'model' | 'hasKey'>[]
  activeProfileId: string | null
  autoGenerate: boolean
}
export type RuntimeConfig = {
  profileId: string
  revision: string
  name: string
  baseUrl: string
  model: string
  stream: boolean
  apiKey: string
  parameters: Record<string, JsonValue>
}
export type ModelEntry = { id: string; selectable: boolean }
export type ModelOperation = {
  id: string
  kind: 'models' | 'check'
  state: 'queued' | 'running' | 'completed' | 'failed'
  error: { code: string; message: string } | null
  result: {
    models?: ModelEntry[]
    hasMore?: boolean
    updatedAt?: number
    elapsedMs?: number
    message?: string
  } | null
}
export type SummaryInputMode = 'speakers' | 'text'
export type SummaryCitation = { text: string; sources: string[] }
export type SummaryAction = {
  task: string
  owner: string | null
  deadline: string | null
  status: string | null
  sources: string[]
}
export type SummaryContentV1 = {
  version: 1
  title: string
  abstract: string
  topics: string[]
  decisions: { text: string; sources: string[] }[]
  actions: SummaryAction[]
  risks: string[]
  openQuestions: string[]
}
export type SummaryContentV2 = {
  version: 2
  title: string
  abstract: string
  overviewSources: string[]
  topics: SummaryCitation[]
  speakerSummaries: {
    speakerId: string
    name: string
    points: SummaryCitation[]
    commitments: SummaryCitation[]
  }[]
  agreements: SummaryCitation[]
  decisions: SummaryCitation[]
  disagreements: SummaryCitation[]
  actions: (SummaryAction & { dependencies: string | null; blocker: string | null })[]
  risks: SummaryCitation[]
  openQuestions: SummaryCitation[]
  suggestions: SummaryCitation[]
}
export type SummaryContent = SummaryContentV1 | SummaryContentV2

export function summaryGenerateInput(
  args: unknown[],
): { meetingId: string; inputMode: SummaryInputMode } | null {
  if (
    (args.length !== 1 && args.length !== 2) ||
    typeof args[0] !== 'string' ||
    !ID_PATTERN.test(args[0]) ||
    (args[1] !== undefined && args[1] !== 'speakers' && args[1] !== 'text')
  )
    return null
  return { meetingId: args[0], inputMode: args[1] ?? 'speakers' }
}
export type SummaryView = {
  task: {
    id: string
    meetingId: string
    state: 'waiting_speakers' | 'queued' | 'running' | 'completed' | 'failed' | 'interrupted'
    error: string | null
    errorCode: string | null
  } | null
  result: {
    meetingId: string
    generatedAt: string
    serviceName: string
    model: string
    stale?: boolean
    sourceIncomplete: boolean
    inputMode?: SummaryInputMode
    speakerIncomplete?: boolean
    parameters: Record<string, JsonValue>
    content: SummaryContent
  } | null
}
export type SummarySource = { id: string; startMs: number; endMs: number; text: string }
