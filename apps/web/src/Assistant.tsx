import { BusinessReply, BusinessSources } from './BusinessSources'
import { useEffect, useRef, useState, useMemo } from 'react'
import { Link, useLocation, useParams } from 'react-router'
import {
  ImagePlus,
  FileText,
  Mic,
  Send,
  Square,
  X,
  Sparkles,
  Check,
  Pencil,
  CornerUpLeft,
} from 'lucide-react'
import type { Attachment, Draft, Page, Progress, Work, WorkMessage } from '@paa/api-contracts'
import { api, ApiError, dateLabel, useResource, write } from './api'
import { usePagedResource } from './paged-resource'
import { AudioCapture, appendRecordedFile, type CaptureState, type Composer } from './audio-capture'
import { progressEditValue, type ProgressEdit } from './progress-edit'
import { useWorkspace } from './workspace'
import { DocumentCard, DocumentCitations } from './Documents'
import { fileAccept, fileKind, fileSelectionError, fileSize, updateSendingDraft } from './files'
import { detailState, detailReturn } from './navigation'
import { AutoTextarea, BusyButton, ConflictRecovery, Empty, ErrorNotice, Modal, Status } from './ui'

export function ConversationChat({
  conversationId,
  onSent,
}: {
  conversationId?: string
  onSent: (conversationId: string) => void
}) {
  const composerKey = `composer:${conversationId ?? 'new'}`
  const { drafts, setDraft, notify, identity } = useWorkspace()
  const storedComposer = drafts[composerKey] as Composer | undefined
  const composer = useMemo(
    () => storedComposer ?? { text: '', files: [], key: '' },
    [storedComposer],
  )
  const { data, error, refresh, loadMore, loading } = usePagedResource<WorkMessage>(
    conversationId ? `/messages?conversationId=${conversationId}` : null,
    'createdAt',
    2000,
  )
  const [sending, setBusy] = useState(false)
  const busy = sending || !!composer.sending
  const [sendError, setSendError] = useState('')
  const [limitError, setLimitError] = useState('')
  const [captureState, setCaptureState] = useState<CaptureState>('idle')
  const recording = captureState === 'recording'
  const capturing = captureState !== 'idle'
  const [seconds, setSeconds] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  const textInput = useRef<HTMLTextAreaElement>(null)
  const capture = useRef<AudioCapture | null>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const active = useRef(true)
  const composerRef = useRef(composer)
  useEffect(() => {
    composerRef.current = composer
  }, [composer])
  const change = (next: Composer) =>
    setDraft(
      composerKey,
      next.text || next.files.length || next.replyTo
        ? { ...next, key: next.key || crypto.randomUUID() }
        : undefined,
    )
  useEffect(() => {
    active.current = true
    const controller = new AudioCapture({
      state: (state) => {
        setCaptureState(state)
        if (state === 'recording') setSeconds(0)
        setDraft('recording', state !== 'idle' ? true : undefined)
      },
      error: setSendError,
      file: (file) => {
        setDraft(composerKey, (previous: Composer | undefined) =>
          appendRecordedFile(previous, file),
        )
      },
    })
    capture.current = controller
    const guard = () => {
      if (document.hidden) controller.stop()
    }
    document.addEventListener('visibilitychange', guard)
    return () => {
      active.current = false
      controller.dispose()
      capture.current = null
      setDraft('recording', undefined)
      document.removeEventListener('visibilitychange', guard)
    }
    // Workspace's setter writes through to the current draft store. Capture owns a
    // single mount session; replacing it on every composer update would stop audio.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useEffect(() => {
    if (!recording) return
    const controller = capture.current
    const timer = setInterval(() => setSeconds((n) => n + 1), 1000)
    const limit = setTimeout(() => {
      controller?.stop()
      setLimitError('已达到 3 分钟录音上限，已保留录音片段，可以试听后发送。')
    }, 180000)
    return () => {
      clearInterval(timer)
      clearTimeout(limit)
    }
  }, [recording])
  const latestId = data?.items[0]?.id
  useEffect(() => {
    if (scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight
  }, [latestId])
  async function addFiles(files: File[]) {
    if (!files.length) return
    const existing = composerRef.current
    const error = fileSelectionError([...existing.files.map((item) => item.file), ...files])
    if (error) {
      setLimitError(error)
      return
    }
    change({
      ...existing,
      key: '',
      files: [
        ...existing.files,
        ...files.map((file) => ({ id: crypto.randomUUID(), file, url: URL.createObjectURL(file) })),
      ],
    })
    setSendError('')
  }
  async function startRecording() {
    if (composer.files.length) {
      setLimitError('请先发送或移除已有附件')
      return
    }
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setSendError('当前浏览器无法录音，请使用安全的 HTTPS 地址，或通过“文件”选择语音、输入文字')
      return
    }
    setSendError('')
    await capture.current?.start()
  }
  async function send() {
    if (busy || capturing || (!composer.text.trim() && !composer.files.length)) return
    setBusy(true)
    setSendError('')
    let current = composer
    setDraft(composerKey, { ...composer, sending: true })
    try {
      const files = [...composer.files]
      for (let i = 0; i < files.length; i++) {
        if (!files[i].attachment) {
          setDraft(composerKey, (previous: Composer | undefined) =>
            updateSendingDraft(previous, composer.key, { uploading: files[i].id }),
          )
          const form = new FormData()
          form.append('file', files[i].file)
          files[i] = {
            ...files[i],
            attachment: await api<Attachment>('/uploads', { method: 'POST', body: form }),
          }
        }
        current = { ...current, files }
        setDraft(composerKey, (previous: Composer | undefined) =>
          updateSendingDraft(previous, composer.key, { files, uploading: undefined }),
        )
      }
      const sent = await write<{ conversationId: string }>(
        '/messages',
        {
          conversationId,
          text: current.text,
          attachmentIds: files.map((f) => f.attachment!.id),
          replyTo: current.replyTo ?? null,
        },
        'POST',
        current.key,
      )
      files.forEach((f) => URL.revokeObjectURL(f.url))
      setDraft(composerKey, (previous: Composer | undefined) =>
        updateSendingDraft(previous, composer.key, null),
      )
      refresh()
      notify('已发送')
      if (active.current) onSent(sent.conversationId)
    } catch (e) {
      if (e instanceof ApiError && [413, 415, 422].includes(e.status) && current.files.length)
        setLimitError(e.message)
      else setSendError((e as Error).message)
    } finally {
      setDraft(composerKey, (previous: Composer | undefined) =>
        updateSendingDraft(previous, composer.key, { sending: false, uploading: undefined }),
      )
      setBusy(false)
    }
  }
  const messages = [...(data?.items ?? [])].sort((a, b) => a.createdAt.localeCompare(b.createdAt))
  const nextCursor = data?.nextCursor
  return (
    <div className="assistant-page">
      {limitError && (
        <Modal title="无法添加附件" onClose={() => setLimitError('')}>
          <p>{limitError}</p>
          <div className="form-actions">
            <button className="primary" onClick={() => setLimitError('')}>
              知道了
            </button>
          </div>
        </Modal>
      )}
      <div className="chat-scroll" ref={scroller}>
        <div className="chat-content">
          <ErrorNotice retry={refresh}>{error}</ErrorNotice>
          {nextCursor && (
            <button className="load-more" disabled={loading} onClick={loadMore}>
              加载更早消息
            </button>
          )}
          {!messages.length && !error && (
            <Empty title={identity.member.role === 'admin' ? '从团队进展开始' : '从今天的工作开始'}>
              {identity.member.role === 'admin' ? (
                <span className="assistant-examples">
                  {['团队当前有哪些阻碍？', '本周员工有哪些工作进展？', '查看最近提交的周报'].map(
                    (text) => (
                      <button
                        key={text}
                        onClick={() => {
                          change({ ...composer, text })
                          textInput.current?.focus()
                        }}
                      >
                        {text}
                      </button>
                    ),
                  )}
                </span>
              ) : (
                '发送进展、文件、现场图片或语音，工作助手会帮你整理。你确认后，再计入工作记录。'
              )}
            </Empty>
          )}
          {messages.map((message) => (
            <MessageCard
              key={message.id}
              message={message}
              own
              onChange={refresh}
              onReply={
                busy
                  ? undefined
                  : () => {
                      change({ ...composer, replyTo: message.id, key: '' })
                      textInput.current?.focus()
                    }
              }
            />
          ))}
        </div>
      </div>
      <div className="composer-wrap">
        <div className="composer">
          {composer.replyTo && (
            <div className="replying">
              <CornerUpLeft size={14} />
              正在补充此前消息
              <button
                className="icon-button"
                aria-label="取消补充关联"
                disabled={busy}
                onClick={() => change({ ...composer, replyTo: undefined, key: '' })}
              >
                <X size={14} />
              </button>
            </div>
          )}
          {composer.files.length > 0 && (
            <div className="attachments pending">
              {composer.files.map((item) => (
                <div key={item.id} className="pending-file">
                  {fileKind(item.file) === 'image' ? (
                    <img src={item.url} alt={item.file.name} />
                  ) : fileKind(item.file) === 'audio' ? (
                    <audio controls src={item.url} preload="metadata" />
                  ) : (
                    <FileText size={24} />
                  )}
                  <div className="pending-file-info">
                    <strong>{item.file.name}</strong>
                    <span>
                      {item.file.name.split('.').pop()?.toUpperCase()} · {fileSize(item.file.size)}{' '}
                      ·{' '}
                      {composer.uploading === item.id
                        ? '正在上传…'
                        : item.attachment
                          ? '上传完成'
                          : '待上传'}
                    </span>
                  </div>
                  <button
                    className="icon-button"
                    disabled={busy}
                    aria-label={`移除${item.file.name}`}
                    onClick={() => {
                      URL.revokeObjectURL(item.url)
                      change({
                        ...composer,
                        key: '',
                        files: composer.files.filter((f) => f.id !== item.id),
                      })
                    }}
                  >
                    <X size={15} />
                  </button>
                </div>
              ))}
            </div>
          )}
          <textarea
            ref={textInput}
            aria-label="工作消息"
            placeholder="今天有什么进展？也可以随时补充一条消息…"
            rows={1}
            maxLength={8000}
            value={composer.text}
            disabled={busy}
            onChange={(e) => change({ ...composer, text: e.target.value, key: '' })}
          />
          <ErrorNotice>{sendError}</ErrorNotice>
          <div className="composer-actions">
            <div>
              <input
                ref={input}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                multiple
                hidden
                onChange={(e) => {
                  void addFiles(Array.from(e.target.files ?? []))
                  e.target.value = ''
                }}
              />
              <button
                className="icon-button"
                aria-label="添加图片"
                title="添加图片"
                disabled={busy || capturing}
                onClick={() => input.current?.click()}
              >
                <ImagePlus size={20} />
              </button>
              {capturing ? (
                <button
                  className="recording"
                  disabled={captureState === 'stopping'}
                  onClick={() => capture.current?.stop()}
                >
                  <Square size={15} />
                  {captureState === 'requesting'
                    ? '取消麦克风申请'
                    : captureState === 'stopping'
                      ? '正在结束录音…'
                      : `停止 · ${seconds} 秒`}
                </button>
              ) : (
                <button
                  className="icon-button"
                  title="录制语音"
                  aria-label="录制语音"
                  disabled={busy}
                  onClick={startRecording}
                >
                  <Mic size={20} />
                </button>
              )}
              <label className="file-label">
                文件
                <input
                  type="file"
                  accept={fileAccept}
                  multiple
                  hidden
                  disabled={busy || capturing}
                  onChange={(e) => {
                    void addFiles(Array.from(e.target.files ?? []))
                    e.target.value = ''
                  }}
                />
              </label>
            </div>
            <BusyButton
              busy={busy}
              className="primary"
              disabled={capturing || (!composer.text.trim() && !composer.files.length)}
              onClick={send}
            >
              <Send size={16} />
              发送
            </BusyButton>
          </div>
        </div>
      </div>
    </div>
  )
}
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
  const location = useLocation()
  const [editing, setEditing] = useState<Draft | null>(null)
  const [transcript, setTranscript] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const { notify, drafts: storedDrafts, setDraft } = useWorkspace()
  useEffect(() => {
    if (message.businessUnavailable && editing && storedDrafts[`progress:${editing.id}`])
      setDraft(`progress:${editing.id}`, undefined)
  }, [message.businessUnavailable, editing, storedDrafts, setDraft])
  const act = async (drafts: Draft[], action: 'confirm' | 'ignore') => {
    setBusy(true)
    try {
      await write(
        `/progress-drafts/${action}`,
        { items: drafts.map((d) => ({ id: d.id, expectedRevision: d.revision })) },
        'POST',
        crypto.randomUUID(),
      )
      onChange()
      notify(action === 'confirm' ? '已更新到我的工作' : '已忽略建议')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const pending = message.drafts.filter((d) => d.status === 'pending')
  return (
    <article className="message">
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
      <div className="attachments">
        {message.attachments.map((a) =>
          a.kind === 'image' ? (
            <a key={a.id} href={a.url} target="_blank" rel="noreferrer">
              <img src={a.url} alt={a.name} loading="lazy" />
            </a>
          ) : a.kind === 'document' ? (
            <DocumentCard key={a.id} attachment={a} own={own} refresh={onChange} />
          ) : (
            <audio key={a.id} controls src={a.url} preload="metadata" aria-label={a.name} />
          ),
        )}
      </div>
      {(message.transcript || message.attachments.some((a) => a.kind === 'audio')) && (
        <div className="transcript">
          <span className="eyebrow">语音文字</span>
          <p className="preserve">{message.transcript || '等待识别'}</p>
          {own && (
            <button className="text-button" onClick={() => setTranscript(true)}>
              修正文字
            </button>
          )}
        </div>
      )}
      {message.businessUnavailable && (
        <p className="notice">这条回答的关联资料或权限已变化，请重新提问。</p>
      )}
      {message.job && <JobNotice job={message.job} refresh={onChange} />}
      {message.reply && (
        <div className="assistant-reply">
          <h3>
            <Sparkles size={16} />
            工作助手
          </h3>
          <BusinessReply
            text={message.reply}
            sources={message.businessCitations ?? []}
            endpoint={`/business-sources/${message.id}`}
          />
          <DocumentCitations citations={message.citations ?? []} />
        </div>
      )}
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
                endpoint={`/business-sources/${message.id}`}
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
      {transcript && (
        <Modal title="修正语音文字" onClose={() => setTranscript(false)}>
          <form
            onSubmit={async (e) => {
              e.preventDefault()
              const text = new FormData(e.currentTarget).get('text')
              setBusy(true)
              try {
                await write(
                  `/messages/${message.id}/transcript`,
                  { text, expectedRevision: message.transcriptRevision },
                  'PATCH',
                )
                setTranscript(false)
                onChange()
              } catch (e) {
                setError((e as Error).message)
              } finally {
                setBusy(false)
              }
            }}
          >
            <AutoTextarea
              name="text"
              rows={3}
              defaultValue={message.transcript}
              maxLength={8000}
              required
            />
            <div className="form-actions">
              <button type="button" onClick={() => setTranscript(false)}>
                取消
              </button>
              <BusyButton busy={busy} className="primary">
                保存修正
              </BusyButton>
            </div>
          </form>
        </Modal>
      )}
    </article>
  )
}
export function JobNotice({
  job,
  refresh,
}: {
  job: NonNullable<WorkMessage['job']>
  refresh: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  if (job.state === 'succeeded' || job.state === 'cancelled') return null
  if (job.state === 'awaiting_input')
    return <p className="muted small-text">可继续发送消息补充信息。</p>
  if (job.state === 'queued' || job.state === 'running')
    return (
      <p className="processing" role="status">
        {job.state === 'queued' ? '已发送，等待整理…' : '正在整理…'}
      </p>
    )
  return (
    <div className="notice error">
      <span>{error || job.error}</span>
      <BusyButton
        busy={busy}
        onClick={async () => {
          if (
            job.state === 'awaiting_retry' &&
            !window.confirm('服务可能已处理过这次请求，重试可能重复计费。继续重试？')
          )
            return
          setBusy(true)
          try {
            await write(`/jobs/${job.id}/retry`, {})
            refresh()
          } catch (e) {
            setError((e as Error).message)
          } finally {
            setBusy(false)
          }
        }}
      >
        重试处理
      </BusyButton>
      <BusyButton
        busy={busy}
        onClick={async () => {
          if (
            !window.confirm(
              '使用管理员当前分配的模型重新处理？这是一次新的处理尝试，可能再次计费；已确认内容保留。',
            )
          )
            return
          setBusy(true)
          try {
            await write(`/jobs/${job.id}/retry`, { useCurrentConfig: true })
            refresh()
          } catch (e) {
            setError((e as Error).message)
          } finally {
            setBusy(false)
          }
        }}
      >
        使用当前配置重新处理
      </BusyButton>
    </div>
  )
}
export function ProgressFields({
  value,
  change,
}: {
  value: Progress
  change: (value: Progress) => void
}) {
  return (
    <>
      <label>
        工作事项
        <input
          value={value.title}
          required
          maxLength={200}
          onChange={(e) => change({ ...value, title: e.target.value })}
        />
      </label>
      <label>
        当前进展
        <AutoTextarea
          rows={3}
          value={value.summary}
          required
          maxLength={4000}
          onChange={(e) => change({ ...value, summary: e.target.value })}
        />
      </label>
      <label>
        状态
        <select
          value={value.status}
          onChange={(e) => change({ ...value, status: e.target.value as Progress['status'] })}
        >
          <option value="in_progress">进行中</option>
          <option value="blocked">有阻碍</option>
          <option value="done">整个事项已完成</option>
        </select>
      </label>
      <label>
        问题或阻碍
        <AutoTextarea
          rows={2}
          value={value.blocker}
          maxLength={2000}
          onChange={(e) => change({ ...value, blocker: e.target.value })}
        />
      </label>
      <label>
        下一步
        <AutoTextarea
          rows={2}
          value={value.nextStep}
          maxLength={2000}
          onChange={(e) => change({ ...value, nextStep: e.target.value })}
        />
      </label>
    </>
  )
}
function ProgressEditor({
  draft,
  onClose,
  onSaved,
}: {
  draft: Draft
  onClose: () => void
  onSaved: () => void
}) {
  const { drafts, setDraft } = useWorkspace()
  const key = `progress:${draft.id}`
  const stored = drafts[key] as ProgressEdit | undefined
  const edited = progressEditValue(draft, stored)
  const { content: value, workId, revision } = edited
  const { data } = useResource<Page<Work>>('/work-items')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const change = (content: Progress, nextWork = workId) =>
    setDraft(key, { content, workId: nextWork, revision })
  return (
    <Modal title="编辑进展建议" onClose={onClose}>
      <form
        onSubmit={async (e) => {
          e.preventDefault()
          setBusy(true)
          try {
            await write(
              `/progress-drafts/${draft.id}`,
              { ...value, workId, expectedRevision: revision },
              'PATCH',
            )
            setDraft(key, undefined)
            onSaved()
          } catch (e) {
            setError((e as Error).message)
          } finally {
            setBusy(false)
          }
        }}
      >
        <label>
          关联工作
          <select value={workId ?? ''} onChange={(e) => change(value, e.target.value || null)}>
            <option value="">新建工作事项</option>
            {data?.items.map((w) => (
              <option key={w.id} value={w.id}>
                {w.title}
              </option>
            ))}
          </select>
        </label>
        <ProgressFields value={value} change={change} />
        <ErrorNotice>{error}</ErrorNotice>
        {error && (
          <ConflictRecovery<Draft>
            load={async () => {
              const message = await api<WorkMessage>(`/messages/${draft.messageId}`)
              const latest = message.drafts.find((d) => d.id === draft.id)
              if (!latest) throw new Error('这条建议已不再可用')
              return latest
            }}
            render={(latest) => (
              <>
                <p>
                  {latest.content.title}：{latest.content.summary}
                </p>
                <p>{latest.content.blocker}</p>
                <p>{latest.content.nextStep}</p>
              </>
            )}
            keep={(latest) => {
              setDraft(key, { ...edited, revision: latest.revision })
              setError('')
            }}
            replace={(latest) => {
              setDraft(key, {
                content: latest.content,
                workId: latest.workId,
                revision: latest.revision,
              })
              setError('')
            }}
          />
        )}
        <div className="form-actions">
          <button type="button" onClick={onClose}>
            稍后继续
          </button>
          <BusyButton busy={busy} className="primary">
            保存修改
          </BusyButton>
        </div>
      </form>
    </Modal>
  )
}
export function SourcePage() {
  const { id } = useParams()
  const { identity } = useWorkspace()
  const { data, error, refresh } = useResource<WorkMessage>(`/messages/${id}`, 2000)
  const location = useLocation()
  const context = detailReturn(location.pathname, location.state)
  return (
    <div className="page narrow">
      <div className="page-heading">
        <div>
          <h2>原始上报</h2>
          <p>来源：{context.label}</p>
        </div>
      </div>
      <ErrorNotice retry={refresh}>{error}</ErrorNotice>
      {data && (
        <MessageCard message={data} own={data.ownerId === identity.member.id} onChange={refresh} />
      )}
    </div>
  )
}
