export type JsonValue =
  null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue }
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
export type SummaryContent = {
  version: 1
  title: string
  abstract: string
  topics: string[]
  decisions: { text: string; sources: string[] }[]
  actions: {
    task: string
    owner: string | null
    deadline: string | null
    status: string | null
    sources: string[]
  }[]
  risks: string[]
  openQuestions: string[]
}
export type SummaryView = {
  task: {
    id: string
    meetingId: string
    state: 'queued' | 'running' | 'completed' | 'failed' | 'interrupted'
    error: string | null
    errorCode: string | null
  } | null
  result: {
    meetingId: string
    generatedAt: string
    serviceName: string
    model: string
    sourceIncomplete: boolean
    parameters: Record<string, JsonValue>
    content: SummaryContent
  } | null
}
export type SummarySource = { id: string; startMs: number; endMs: number; text: string }
