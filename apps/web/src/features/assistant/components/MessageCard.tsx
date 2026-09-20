import type { Draft, WorkMessage } from '@paa/api-contracts'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Status } from '@web/components/Status'
import { resolveProgressDrafts } from '@web/features/assistant/api/requests'
import { BusinessActionCard } from '@web/features/assistant/components/BusinessActionCard'
import { DocumentCard, DocumentCitations } from '@web/features/assistant/components/Documents'
import { ImageGallery } from '@web/features/assistant/components/ImageGallery'
import { MessageTranscript } from '@web/features/assistant/components/MessageTranscript'
import { TranscriptEditor } from '@web/features/assistant/components/TranscriptEditor'
import { JobNotice } from '@web/features/jobs/components/JobNotice'
import { messageSourcesPath } from '@web/features/sources/api/requests'
import { BusinessReply, BusinessSources } from '@web/features/sources/components/BusinessSources'
import { ProgressEditor } from '@web/features/work/components/ProgressEditor'
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
  onReply,
}: {
  message: WorkMessage
  own?: boolean
  onChange: () => void
  onReply?: () => void
}) {
  const live = useJobFeedback(message.job, own && !message.businessUnavailable, onChange)
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
  return (
    <article className="message">
      {gallery !== null && !message.businessUnavailable && images[gallery] && (
        <ImageGallery images={images} initial={gallery} onClose={() => setGallery(null)} />
      )}
      <header>
        <span className="eyebrow">工作消息</span>
        <time>{dateLabel(message.createdAt)}</time>
        {onReply && (
          <button className="text-button" onClick={onReply}>
            补充
          </button>
        )}
      </header>
      {message.text && <p className="preserve">{message.text}</p>}
      <div className="attachment-groups">
        {(['audio', 'image', 'document'] as const).map((kind) => {
          const items = message.attachments.filter((a) => a.kind === kind)
          return (
            items.length > 0 && (
              <div className={`attachments attachments-${kind}`} key={kind}>
                {items.map((a) =>
                  a.kind === 'image' ? (
                    <button
                      className="attachment-preview-button"
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
      {message.businessUnavailable && (
        <p className="notice">这条回答的关联资料或权限已变化，请重新提问。</p>
      )}
      {message.job && (
        <JobNotice
          job={{
            ...message.job,
            ...(live.feedback
              ? {
                  state: live.feedback.state,
                  stage: live.feedback.stage,
                  error: live.feedback.error,
                }
              : {}),
          }}
          refresh={onChange}
        />
      )}
      {live.error && (
        <p className="muted small-text" role="status">
          {live.error}
        </p>
      )}
      {!message.reply && !message.businessUnavailable && live.feedback?.text && (
        <div className="assistant-reply provisional-reply">
          <small>
            {['queued', 'running'].includes(live.feedback.state)
              ? '生成中，内容尚未完成'
              : '回复未完成'}
          </small>
          <p className="preserve">{live.feedback.text}</p>
        </div>
      )}
      {message.reply && (
        <div className="assistant-reply">
          <h3>
            <Sparkles size={16} />
            工作助手
          </h3>
          <BusinessReply
            text={message.reply}
            sources={message.businessCitations ?? []}
            endpoint={messageSourcesPath(message.id)}
          />
          <DocumentCitations citations={message.citations ?? []} />
        </div>
      )}
      {own &&
        message.actions?.map((action) => (
          <BusinessActionCard key={action.id} action={action} refresh={onChange} />
        ))}
      {own
        ? message.drafts.map((d) => (
            <div className="progress-card" key={d.id}>
              <div className="row-between">
                <h3>{d.content.title}</h3>
                <Status value={d.status} />
              </div>
              <p>{d.content.summary}</p>
              {d.content.blocker && <p className="blocker">阻碍：{d.content.blocker}</p>}
              {d.content.nextStep && <p className="muted">下一步：{d.content.nextStep}</p>}
              <BusinessSources
                sources={d.businessLinks ?? []}
                endpoint={messageSourcesPath(message.id)}
              />
              {d.status === 'pending' && (
                <div className="card-actions">
                  <button
                    className="primary small"
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
                    className="text-button"
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
            <div className="progress-card" key={s.id}>
              <div className="row-between">
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
        setError={setError}
        busy={busy}
      />
    </article>
  )
}
