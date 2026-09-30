import layoutStyles from '../../../../styles/layout.module.css'
import controlsStyles from '../../../../styles/controls.module.css'
import utilitiesStyles from '../../../../styles/utilities.module.css'
import noticeStyles from '../../../../styles/patterns/Notice.module.css'
import styles from './MessageCard.module.css'
import attachmentsStyles from '../../styles/attachments.module.css'
import type { DeliverableReference, Draft, Job, JobFeedback, WorkMessage } from '@paa/api-contracts'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { Status } from '@web/components/feedback/Status'
import { resolveProgressDrafts } from '@web/features/assistant/api/requests'
import type { TaskContinuation } from '../../api/interactions'
import { QuestionHistory } from '../interactions/QuestionPanel'
import { WorkReferenceChip } from '../work-reference/WorkReferenceChip'
import { DeliverableEntry } from '../deliverables/Deliverable'
import { BusinessActionCard } from '@web/features/assistant/components/interactions/BusinessActionCard'
import {
  DocumentCard,
  DocumentCitations,
} from '@web/features/assistant/components/attachments/Documents'
import { ImageGallery } from '@web/features/assistant/components/attachments/ImageGallery'
import { MessageTranscript } from '@web/features/assistant/components/messages/MessageTranscript'
import { TranscriptEditor } from '@web/features/assistant/components/messages/TranscriptEditor'
import { JobNotice } from '@web/features/jobs/components/JobNotice'
import { messageSourcesPath } from '@web/features/sources/api/requests'
import { BusinessReply, BusinessSources } from '@web/features/sources/components/BusinessSources'
import { ProgressEditor } from '@web/features/work/components/editor/ProgressEditor'
import { useJobFeedback } from '@web/hooks/useJobFeedback'
import { useWorkspace } from '@web/lib/workspace'
import { dateLabel } from '@web/utils/date'
import { detailState } from '@web/utils/navigation'
import { Check, Pencil, Sparkles } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router'

export function MessageCard({
  message,
  own = false,
  onChange,
  onFeedback,
  onReply,
  onDeliverable,
  onContextUpdate,
  onContinuation,
  hiddenActionMessageIds,
  activeJob,
  retryBlocked,
  onRetryStart,
  onRetrySettled,
}: {
  onContinuation?: (continuation?: TaskContinuation) => void
  hiddenActionMessageIds?: ReadonlySet<string>
  message: WorkMessage
  activeJob?: Job | null
  retryBlocked?: boolean
  onRetryStart?: () => boolean
  onRetrySettled?: (job: Job | null) => void
  own?: boolean
  onChange: () => void
  onFeedback?: (feedback?: JobFeedback) => void
  onReply?: () => void
  onContextUpdate?: (job: Job, feedback: JobFeedback | null) => void
  onDeliverable?: (reference: DeliverableReference, title: string, text?: string) => void
}) {
  const [retriedJob, setRetriedJob] = useState<Job | null>(null)
  // Keep the new attempt visible while the message refresh is still in flight.
  // Older SSE snapshots must not restore the response that was just replaced.
  const replacing =
    retriedJob?.id === message.job?.id && (retriedJob?.attempt ?? 0) > (message.job?.attempt ?? 0)
  const sourceJob = replacing ? retriedJob : message.job
  const job =
    activeJob?.id === sourceJob?.id &&
    (activeJob?.attempt ?? 0) >= (sourceJob?.attempt ?? 0) &&
    (activeJob?.fence ?? 0) >= (sourceJob?.fence ?? 0) &&
    ((activeJob?.attempt ?? 0) > (sourceJob?.attempt ?? 0) ||
      (activeJob?.fence ?? 0) > (sourceJob?.fence ?? 0) ||
      (sourceJob && ['queued', 'running'].includes(sourceJob.state)) ||
      (activeJob && !['queued', 'running'].includes(activeJob.state)))
      ? activeJob!
      : sourceJob
  const live = useJobFeedback(job, own && !message.businessUnavailable, onFeedback ?? onChange)
  useEffect(() => {
    if (own && !message.businessUnavailable && job) onContextUpdate?.(job, live.feedback)
  }, [own, message.businessUnavailable, job, live.feedback, onContextUpdate])
  const failed = ['failed', 'awaiting_retry', 'cancelled'].includes(
    live.feedback?.state ?? job?.state ?? '',
  )
  const location = useLocation()
  const [editing, setEditing] = useState<Draft | null>(null)
  const [gallery, setGallery] = useState<number | null>(null)
  const images = message.attachments
    .filter((item) => item.kind === 'image')
    .map((item) => ({
      id: item.id,
      name: item.name,
      src: item.previewUrl ?? item.url,
      original: item.url,
      warnings: item.image?.warnings,
    }))
  const [transcript, setTranscript] = useState(false)
  const [transcriptOpen, setTranscriptOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  const { notify, drafts: storedDrafts, setDraft } = useWorkspace()
  useEffect(() => {
    if (message.businessUnavailable && editing && storedDrafts[`progress:${editing.id}`])
      setDraft(`progress:${editing.id}`, undefined)
  }, [message.businessUnavailable, editing, storedDrafts, setDraft])
  const act = async (drafts: Draft[], action: 'confirm' | 'ignore') => {
    setBusy(true)
    try {
      await resolveProgressDrafts(
        action,
        { items: drafts.map((d) => ({ id: d.id, expectedRevision: d.revision })) },
        crypto.randomUUID(),
      )
      onChange()
      notify(action === 'confirm' ? '已更新到我的工作' : '已忽略建议')
    } catch (e) {
      setError(e as Error)
    } finally {
      setBusy(false)
    }
  }
  const pending = message.drafts.filter((d) => d.status === 'pending')
  const hasAssistant = !!(
    message.reply ||
    message.job ||
    message.businessUnavailable ||
    message.drafts.length ||
    message.suggestions.length
  )
  return (
    <article className={styles['message']}>
      {gallery !== null && !message.businessUnavailable && images[gallery] && (
        <ImageGallery images={images} initial={gallery} onClose={() => setGallery(null)} />
      )}
      <div className={styles['user-turn']}>
        <header>
          <span className={layoutStyles['eyebrow']}>{own ? '你' : '工作消息'}</span>
          <time>{dateLabel(message.createdAt)}</time>
          {onReply && (
            <button
              className={`${controlsStyles['text-button']} ${styles['slot-text-button']}`}
              onClick={onReply}
            >
              补充
            </button>
          )}
        </header>
        {message.workReference && <WorkReferenceChip reference={message.workReference} linked />}
        {message.text && (
          <p className={`${utilitiesStyles['preserve']} ${styles['user-bubble']}`}>
            {message.text}
          </p>
        )}
        <div className={styles['user-attachments']}>
          {(['audio', 'image', 'document'] as const).map((kind) => {
            const items = message.attachments.filter((a) => a.kind === kind)
            return (
              items.length > 0 && (
                <div className={attachmentsStyles['attachments']} data-kind={kind} key={kind}>
                  {items.map((a) =>
                    a.kind === 'image' ? (
                      <button
                        className={attachmentsStyles['attachment-preview-button']}
                        key={a.id}
                        aria-label={`预览${a.name}`}
                        onClick={() => setGallery(images.findIndex((item) => item.id === a.id))}
                      >
                        <img src={a.previewUrl ?? a.url} alt={a.name} loading="lazy" />
                      </button>
                    ) : a.kind === 'document' ? (
                      <DocumentCard key={a.id} attachment={a} own={own} refresh={onChange} />
                    ) : (
                      <audio
                        key={a.id}
                        controls
                        src={a.previewUrl ?? a.url}
                        preload="metadata"
                        aria-label={a.name}
                      />
                    ),
                  )}
                </div>
              )
            )
          })}
        </div>
        {(message.transcript || message.attachments.some((a) => a.kind === 'audio')) && (
          <MessageTranscript
            transcriptOpen={transcriptOpen}
            message={message}
            setTranscriptOpen={setTranscriptOpen}
            own={own}
            setTranscript={setTranscript}
          />
        )}
      </div>
      {hasAssistant && (
        <div className={styles['assistant-turn']}>
          <h3 className={styles['assistant-identity']}>
            <Sparkles size={16} />
            Noria
          </h3>
          {message.businessUnavailable && (
            <p className={noticeStyles['notice']}>这条回答的关联资料或权限已变化，请重新提问。</p>
          )}
          {job && (
            <JobNotice
              job={{
                ...job,
                ...(live.feedback
                  ? {
                      state: live.feedback.state,
                      taskOutcome: live.feedback.taskOutcome ?? job.taskOutcome,
                      incompleteTask: live.feedback.incompleteTask ?? job.incompleteTask,
                      stage: live.feedback.stage,
                      error: live.feedback.error,
                      nodes: live.feedback.nodes,
                      attempt: live.feedback.attempt,
                      fence: live.feedback.fence,
                    }
                  : {}),
              }}
              refresh={onChange}
              onRetryJob={setRetriedJob}
              retryBlocked={retryBlocked}
              onRetryStart={onRetryStart}
              onRetrySettled={onRetrySettled}
              showNodes
            />
          )}
          {own &&
            !message.businessUnavailable &&
            !failed &&
            job?.operationFeedback?.map((item) => (
              <div className={noticeStyles['notice']} role="status" key={item.step}>
                <strong>
                  {item.label} ·{' '}
                  {item.state === 'clarification'
                    ? '需要补充'
                    : item.state === 'waiting'
                      ? '等待前置操作'
                      : '未执行'}
                </strong>
                <p>{item.message}</p>
              </div>
            ))}
          {live.error && !replacing && activeJob?.id !== job?.id && (
            <ErrorNotice retry={() => void live.reconnect()}>{live.error}</ErrorNotice>
          )}
          {(!message.reply || replacing) &&
            !failed &&
            !message.businessUnavailable &&
            live.feedback?.text && (
              <div className={`${styles['assistant-reply']} ${styles['provisional-reply']}`}>
                <small>
                  {['queued', 'running'].includes(live.feedback.state)
                    ? '生成中，内容尚未完成'
                    : '回复未完成'}
                </small>
                <p className={utilitiesStyles['preserve']}>{live.feedback.text}</p>
              </div>
            )}
          {message.reply && !replacing && !failed && (
            <div className={styles['assistant-reply']}>
              <BusinessReply
                text={message.reply}
                sources={message.businessCitations ?? []}
                endpoint={messageSourcesPath(message.id)}
              />
              <DocumentCitations citations={message.citations ?? []} />
            </div>
          )}
          {own &&
            !message.businessUnavailable &&
            message.deliverables?.map((item) => (
              <DeliverableEntry
                key={`${item.id}:${item.revision}`}
                item={item}
                onContinue={onDeliverable}
              />
            ))}
          {own &&
            !message.businessUnavailable &&
            (live.feedback?.actions ?? message.actions)
              ?.filter((action) => !hiddenActionMessageIds?.has(action.messageId))
              .map((action) => (
                <BusinessActionCard
                  key={action.id}
                  action={action}
                  refresh={onChange}
                  onContinuation={onContinuation}
                />
              ))}
          {own &&
            !message.businessUnavailable &&
            (message.interactions ?? []).map((item) => (
              <QuestionHistory key={item.id} item={item} />
            ))}
          {own
            ? message.drafts.map((d) => (
                <div className={styles['progress-card']} key={d.id}>
                  <div className={`${layoutStyles['row-between']} ${styles['slot-row-between']}`}>
                    <h3>{d.content.title}</h3>
                    <Status value={d.status} />
                  </div>
                  <p>{d.content.summary}</p>
                  {d.content.blocker && (
                    <p className={utilitiesStyles['error-text']}>阻碍：{d.content.blocker}</p>
                  )}
                  {d.content.nextStep && (
                    <p className={utilitiesStyles['muted']}>下一步：{d.content.nextStep}</p>
                  )}
                  <BusinessSources
                    sources={d.businessLinks ?? []}
                    endpoint={messageSourcesPath(message.id)}
                  />
                  {d.status === 'pending' && (
                    <div className={layoutStyles['card-actions']}>
                      <button
                        className={controlsStyles['primary']}
                        disabled={busy}
                        onClick={() => void act([d], 'confirm')}
                      >
                        <Check size={15} />
                        {d.businessLinks?.length ? '确认我的督办' : '确认进展'}
                      </button>
                      <button disabled={busy} onClick={() => setEditing(d)}>
                        <Pencil size={14} />
                        编辑
                      </button>
                      <button
                        className={`${controlsStyles['text-button']} ${styles['slot-text-button']}`}
                        disabled={busy}
                        onClick={() => void act([d], 'ignore')}
                      >
                        忽略
                      </button>
                      <Link to={`/messages/${message.id}`} state={detailState(location)}>
                        查看来源
                      </Link>
                    </div>
                  )}
                </div>
              ))
            : message.suggestions.map((s) => (
                <div className={styles['progress-card']} key={s.id}>
                  <div className={`${layoutStyles['row-between']} ${styles['slot-row-between']}`}>
                    <h3>{s.content.title}</h3>
                    <Status value={s.status} />
                  </div>
                  <p>{s.content.summary}</p>
                </div>
              ))}
          {pending.length > 1 && (
            <button disabled={busy} onClick={() => void act(pending, 'confirm')}>
              确认本轮 {pending.length} 项进展
            </button>
          )}
          <ErrorNotice>{error}</ErrorNotice>
        </div>
      )}
      {editing && !message.businessUnavailable && (
        <ProgressEditor
          draft={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            onChange()
          }}
        />
      )}
      <TranscriptEditor
        transcript={transcript}
        setTranscript={setTranscript}
        setBusy={setBusy}
        message={message}
        onChange={onChange}
        busy={busy}
      />
    </article>
  )
}
