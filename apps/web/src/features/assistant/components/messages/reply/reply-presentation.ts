import type { Job, JobFeedback, WorkMessage } from '@paa/api-contracts'

export function replyPresentation(
  message: WorkMessage,
  job: Job | null,
  feedback: JobFeedback | null,
  own: boolean,
  unavailable = false,
) {
  const attempt = feedback?.attempt ?? job?.attempt ?? 0
  const fence = feedback?.fence ?? job?.fence ?? 0
  const current =
    message.job?.id === job?.id &&
    (message.job?.attempt ?? 0) >= attempt &&
    (message.job?.fence ?? 0) >= fence
  const state = feedback?.state ?? job?.state
  const failed = ['failed', 'awaiting_retry', 'cancelled'].includes(state ?? '')
  // A terminal event alone does not prove that the persisted reply has arrived.
  const delivered =
    !job || (current && ['succeeded', 'awaiting_input'].includes(message.job?.state ?? ''))
  const stream = feedback?.replyStream ?? job?.replyStream ?? (current ? message.replyStream : null)
  const preview =
    own &&
    !message.businessUnavailable &&
    !unavailable &&
    !(delivered && !failed) &&
    stream?.state !== 'withdrawn'
  const text = preview ? (stream ? stream.text : !failed ? (feedback?.text ?? '') : '') : ''
  const activity =
    text && !failed && stream?.state !== 'interrupted'
      ? stream?.state === 'finalizing' || ['succeeded', 'awaiting_input'].includes(state ?? '')
        ? '核对并保存回复'
        : state === 'running'
          ? '生成回答'
          : undefined
      : undefined
  return {
    text,
    stream,
    delivered: delivered && !failed,
    activity,
    animate:
      !!feedback?.replyStream && stream?.state === 'streaming' && state === 'running' && preview,
    identity: JSON.stringify([message.id, job?.id, attempt, fence, stream?.generation ?? 0]),
  }
}
