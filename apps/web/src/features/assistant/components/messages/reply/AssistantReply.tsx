import type { Job, JobFeedback, WorkMessage } from '@paa/api-contracts'
import { Markdown } from '@web/components/content/Markdown'
import { DocumentCitations } from '@web/components/media/Documents'
import { messageSourcesPath } from '@web/features/sources/api/requests'
import { BusinessReply } from '@web/features/sources/components/BusinessSources'
import styles from './AssistantReply.module.css'
import { useStreamingText } from './useStreamingText'
import { replyPresentation } from './reply-presentation'
import { WebSources } from './WebSources'
import { compactImageReferences } from './image-references'

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
  const { text, stream, delivered, animate, identity } = replyPresentation(
    message,
    job,
    feedback,
    own,
    unavailable,
  )
  const displayedText = useStreamingText(text, animate, identity)
  if (message.businessUnavailable || unavailable) return null
  if (delivered) {
    return message.reply ? (
      <div className={styles.reply}>
        <BusinessReply
          text={own ? compactImageReferences(message.reply, message.deliverables) : message.reply}
          sources={message.businessCitations ?? []}
          endpoint={messageSourcesPath(message.id)}
        />
        <DocumentCitations citations={message.citations ?? []} />
        <WebSources sources={message.webSources ?? []} />
      </div>
    ) : null
  }
  if (!own || !text || stream?.state === 'withdrawn') return null
  return (
    <div className={styles.reply} data-reply-state={stream?.state ?? 'streaming'}>
      <Markdown text={displayedText} />
    </div>
  )
}
