import styles from './ChatHistory.module.css'
import messageStyles from './MessageCard.module.css'
import noticeStyles from '../../../../styles/patterns/Notice.module.css'
import type {
  BusinessAction,
  DeliverableReference,
  Identity,
  Job,
  JobFeedback,
  Page,
  WorkMessage,
} from '@paa/api-contracts'
import { BusinessActionCard } from '@web/features/assistant/components/interactions/BusinessActionCard'
import { MessageCard } from '@web/features/assistant/components/messages/MessageCard'
import type { Composer } from '@web/features/assistant/lib/audio-capture'
import { fileKind } from '@web/features/assistant/utils/files'
import { JobNotice } from '@web/features/jobs/components/JobNotice'
import type { TaskContinuation } from '../../api/interactions'
import type { useAssistantTask } from '../../hooks/conversation/useAssistantTask'
import type * as React from 'react'
import { LoaderCircle, Sparkles } from 'lucide-react'

export function ChatHistory({
  scroller,
  atBottomRef,
  setNewReply,
  refresh,
  invalidate,
  onFeedback,
  error,
  nextCursor,
  loading,
  loadMore,
  messages,
  conversationId,
  data,
  locked,
  composer,
  change,
  textInput,
  actionReceipts,
  onDeliverable,
  onContextUpdate,
  onContinuation,
  task,
  sending = false,
}: {
  sending?: boolean
  onContinuation?: (continuation?: TaskContinuation) => void
  task?: ReturnType<typeof useAssistantTask>
  onContextUpdate?: (job: Job, feedback: JobFeedback | null) => void
  onDeliverable?: (reference: DeliverableReference, title: string, text?: string) => void
  scroller: React.RefObject<HTMLDivElement | null>
  atBottomRef: React.RefObject<boolean>
  setNewReply: React.Dispatch<React.SetStateAction<boolean>>
  refresh: () => Promise<void>
  invalidate?: () => Promise<void>
  onFeedback?: (feedback?: JobFeedback) => void
  error: string | Error
  nextCursor: string | null | undefined
  loading: boolean
  loadMore: () => Promise<void>
  messages: WorkMessage[]
  conversationId: string | undefined
  data: Page<WorkMessage> | null
  identity: Identity
  locked: boolean
  composer: Composer
  change: (next: Composer) => void
  textInput: React.RefObject<HTMLTextAreaElement | null>
  actionReceipts: {
    data: { items: BusinessAction[] } | null
    error: string | Error
    refresh: () => void
  }
}) {
  const visibleMessageIds = new Set(messages.map((message) => message.id))
  const pendingJob = task?.job && !visibleMessageIds.has(task.job.targetId) ? task.job : null
  const uploading = composer.files.find((file) => file.id === composer.uploading)
  const sendingLabel = uploading
    ? fileKind(uploading.file) === 'audio'
      ? '正在上传语音…'
      : '正在上传附件…'
    : '正在发送消息…'
  const empty = !messages.length && !sending && !pendingJob && !error && (!conversationId || !!data)
  const standaloneActions =
    actionReceipts.data?.items.filter((action) => !visibleMessageIds.has(action.messageId)) ?? []
  const coveredOrigins = new Set(standaloneActions.map((action) => action.messageId))
  return (
    <div
      className={styles['chat-scroll']}
      data-empty={empty}
      ref={scroller}
      onScroll={() => {
        const node = scroller.current
        if (node) {
          atBottomRef.current = node.scrollHeight - node.scrollTop - node.clientHeight < 80
          if (atBottomRef.current) setNewReply(false)
        }
      }}
    >
      <div className={styles['chat-content']} data-chat-content>
        {nextCursor && (
          <button className={styles['load-more']} disabled={loading} onClick={loadMore}>
            加载更早消息
          </button>
        )}
        {empty && (
          <div className={styles['assistant-welcome']}>
            <div className={styles['welcome-orbit']} aria-hidden="true">
              <span />
              <span />
              <div>
                <Sparkles size={30} />
              </div>
            </div>
            <span className={styles['welcome-eyebrow']}>
              <span />
              你的工作伙伴
            </span>
            <h2>今天，想推进什么？</h2>
            <p>从一个想法、一份材料，或手头的工作开始。</p>
          </div>
        )}
        {standaloneActions.map((action) => (
          <BusinessActionCard
            key={action.id}
            action={action}
            refresh={actionReceipts.refresh}
            onContinuation={onContinuation}
          />
        ))}
        {messages.map((message) => {
          const hiddenActionMessageIds = new Set([...visibleMessageIds, ...coveredOrigins])
          hiddenActionMessageIds.delete(message.id)
          message.actions?.forEach((action) => coveredOrigins.add(action.messageId))
          return (
            <MessageCard
              key={message.id}
              message={message}
              hiddenActionMessageIds={hiddenActionMessageIds}
              activeJob={task?.job}
              retryBlocked={locked || task?.blocked}
              onRetryStart={task?.beginRetry}
              onRetrySettled={task?.finishRetry}
              onContextUpdate={onContextUpdate}
              onContinuation={onContinuation}
              own
              onChange={invalidate ?? refresh}
              onFeedback={onFeedback ?? refresh}
              onDeliverable={locked ? undefined : onDeliverable}
              onReply={
                locked
                  ? undefined
                  : () => {
                      change({ ...composer, replyTo: message.id, key: '' })
                      textInput.current?.focus()
                    }
              }
            />
          )
        })}
        {(sending || pendingJob) && (
          <div className={messageStyles['assistant-turn']} data-pending-assistant>
            <h3 className={messageStyles['assistant-identity']}>
              <Sparkles size={16} />
              Noria
            </h3>
            {sending ||
            (pendingJob && ['succeeded', 'awaiting_input'].includes(pendingJob.state)) ? (
              <p className={noticeStyles.processing} role="status">
                <LoaderCircle size={14} aria-hidden="true" />
                {sending ? sendingLabel : '正在载入回复…'}
              </p>
            ) : pendingJob ? (
              <JobNotice
                job={pendingJob}
                showNodes
                refresh={refresh}
                retryBlocked={locked || task?.blocked}
                onRetryStart={task?.beginRetry}
                onRetrySettled={task?.finishRetry}
              />
            ) : null}
          </div>
        )}
      </div>
    </div>
  )
}
