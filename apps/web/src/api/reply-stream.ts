import type { JobFeedback, ReplyEvent, ReplyStream } from '@paa/api-contracts'

export type ReplyCursor = {
  attempt: number
  fence: number
  generation: number
  seq: number
  reply: ReplyStream
}

// State sequence and reply sequence deliberately have separate orderings.
export function reduceReply(
  current: ReplyCursor | null,
  event: ReplyEvent,
  feedback: JobFeedback,
): ReplyCursor | null {
  if (
    event.jobId !== feedback.jobId ||
    event.attempt !== feedback.attempt ||
    event.fence !== feedback.fence ||
    !['queued', 'running'].includes(feedback.state)
  )
    return current
  const same = current && current.attempt === event.attempt && current.fence === event.fence
  if (
    same &&
    (event.generation < current.generation ||
      (event.generation === current.generation && event.seq <= current.seq))
  )
    return current
  const generation = same && event.generation === current.generation
  if (event.type === 'delta' && (!generation || event.seq !== current.seq + 1)) return current
  return {
    attempt: event.attempt,
    fence: event.fence,
    generation: event.generation,
    seq: event.seq,
    reply: {
      version: 1,
      generation: event.generation,
      state:
        event.type === 'withdrawn'
          ? 'withdrawn'
          : event.state === 'finalizing'
            ? 'finalizing'
            : 'streaming',
      text:
        event.type === 'withdrawn'
          ? ''
          : event.type === 'sync'
            ? (event.text ?? '')
            : (current?.reply.text ?? '') + (event.delta ?? ''),
    },
  }
}
