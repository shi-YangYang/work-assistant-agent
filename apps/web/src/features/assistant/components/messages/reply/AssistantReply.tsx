import type { Job, JobFeedback, WorkMessage } from '@paa/api-contracts'
import { Markdown } from '@web/components/content/Markdown'
import { DocumentCitations } from '@web/components/media/Documents'
import { messageSourcesPath } from '@web/features/sources/api/requests'
import { BusinessReply } from '@web/features/sources/components/BusinessSources'
import styles from './AssistantReply.module.css'
import { useStreamingText } from './useStreamingText'

export function AssistantReply({
  message,
  job,
  feedback,
  own,
  unavailable = false,
}: {
  message: WorkMessage
  job: Job | null
  feedback: JobFeedback | null
  own: boolean
  unavailable?: boolean
}) {
  const attempt = feedback?.attempt ?? job?.attempt ?? 0
  const fence = feedback?.fence ?? job?.fence ?? 0
  const current =
    message.job?.id === job?.id &&
    (message.job?.attempt ?? 0) >= attempt &&
    (message.job?.fence ?? 0) >= fence
  const state = feedback?.state ?? job?.state
  const failed = ['failed', 'awaiting_retry', 'cancelled'].includes(state ?? '')
  // Only a persisted terminal message from this execution replaces the preview.
  // A successful SSE event alone cannot prove the final GET has arrived.
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
  const displayedText = useStreamingText(
    text,
    !!feedback?.replyStream && stream?.state === 'streaming' && state === 'running' && preview,
    JSON.stringify([message.id, job?.id, attempt, fence, stream?.generation ?? 0]),
  )
  if (message.businessUnavailable || unavailable) return null
  if (delivered && !failed) {
    return message.reply ? (
      <div className={styles.reply}>
        <BusinessReply
          text={message.reply}
          sources={message.businessCitations ?? []}
          endpoint={messageSourcesPath(message.id)}
        />
        <DocumentCitations citations={message.citations ?? []} />
      </div>
    ) : null
  }
  if (!own || !text || stream?.state === 'withdrawn') return null
  const label =
    state === 'cancelled'
      ? '已中断'
      : failed || stream?.state === 'interrupted'
        ? '回复未完成'
        : stream?.state === 'finalizing' || ['succeeded', 'awaiting_input'].includes(state ?? '')
          ? '正在核对并保存回复…'
          : '生成中，内容尚未完成'
  return (
    <div className={styles.reply} data-reply-state={stream?.state ?? 'streaming'}>
      <small className={styles.status} role="status">
        {label}
      </small>
      <Markdown text={displayedText} />
    </div>
  )
}
