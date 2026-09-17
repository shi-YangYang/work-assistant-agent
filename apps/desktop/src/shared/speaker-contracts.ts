export type SpeakerStatus = {
  meetingId: string
  generation: string
  state: 'not_started' | 'running' | 'completed' | 'paused' | 'failed'
  revision: number
  device: 'cpu' | 'mps' | 'cuda' | null
  error: string | null
  speakers: { id: string; name: string }[]
  model: { state: 'missing' | 'ready'; error: string | null }
  progress: string
}
export type SpeakerRequest =
  | { action: 'status' | 'start' | 'cancel'; meetingId: string }
  | {
      action: 'rename'
      meetingId: string
      generation: string
      revision: number
      speakerId: string
      name: string
    }
  | {
      action: 'assign'
      meetingId: string
      generation: string
      revision: number
      speakerId: string | null
      segmentId: string
    }

export function validSpeakerRequest(input: unknown): input is SpeakerRequest {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return false
  const value = input as Record<string, unknown>
  const fields: Record<string, string[]> = {
    status: ['action', 'meetingId'],
    start: ['action', 'meetingId'],
    cancel: ['action', 'meetingId'],
    rename: ['action', 'meetingId', 'generation', 'revision', 'speakerId', 'name'],
    assign: ['action', 'meetingId', 'generation', 'revision', 'speakerId', 'segmentId'],
  }
  if (
    typeof value.action !== 'string' ||
    !Object.hasOwn(fields, value.action) ||
    Object.keys(value).sort().join() !== fields[value.action].sort().join()
  )
    return false
  if (
    'meetingId' in value &&
    (typeof value.meetingId !== 'string' ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(
        value.meetingId,
      ))
  )
    return false
  if (
    'generation' in value &&
    (typeof value.generation !== 'string' ||
      value.generation.length > 64 ||
      !Number.isSafeInteger(value.revision) ||
      Number(value.revision) < 0)
  )
    return false
  if (
    'speakerId' in value &&
    !(value.action === 'assign' && value.speakerId === null) &&
    (typeof value.speakerId !== 'string' || !/^speaker_\d{1,3}$/.test(value.speakerId))
  )
    return false
  if (value.action === 'rename')
    return (
      typeof value.name === 'string' &&
      value.name.trim().length > 0 &&
      value.name.length <= 40 &&
      !Array.from(value.name).some((char) => {
        const code = char.charCodeAt(0)
        return code < 32 || (code >= 127 && code < 160) || code === 0x2028 || code === 0x2029
      })
    )
  if (value.action === 'assign')
    return typeof value.segmentId === 'string' && value.segmentId.length <= 64
  return true
}

export function isSpeakerStatus(input: unknown): input is SpeakerStatus {
  if (!input || typeof input !== 'object') return false
  const value = input as SpeakerStatus
  return (
    typeof value.meetingId === 'string' &&
    typeof value.generation === 'string' &&
    ['not_started', 'running', 'completed', 'paused', 'failed'].includes(value.state) &&
    Number.isSafeInteger(value.revision) &&
    value.revision >= 0 &&
    [null, 'cpu', 'mps', 'cuda'].includes(value.device) &&
    (value.error === null || typeof value.error === 'string') &&
    Array.isArray(value.speakers) &&
    value.speakers.length <= 100 &&
    value.speakers.every(
      (speaker) =>
        !!speaker &&
        typeof speaker === 'object' &&
        /^speaker_\d{1,3}$/.test(speaker.id) &&
        typeof speaker.name === 'string' &&
        speaker.name.length <= 40,
    ) &&
    !!value.model &&
    ['missing', 'ready'].includes(value.model.state) &&
    (value.model.error === null || typeof value.model.error === 'string') &&
    typeof value.progress === 'string'
  )
}
