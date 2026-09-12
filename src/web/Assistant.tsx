import { useEffect, useRef, useState, useMemo } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import {
  ImagePlus,
  Mic,
  Send,
  Square,
  X,
  Sparkles,
  Check,
  Pencil,
  CornerUpLeft,
} from 'lucide-react'
import type {
  Attachment,
  Draft,
  Page,
  Progress,
  Work,
  WorkMessage,
} from '../shared/company-contracts'
import { api, dateLabel, useResource, write } from './api'
import { AudioCapture, appendRecordedFile, type CaptureState, type Composer } from './audio-capture'
import { progressEditValue, type ProgressEdit } from './progress-edit'
import { useWorkspace } from './workspace'
import { BusyButton, ConflictRecovery, Empty, ErrorNotice, Modal, Status } from './ui'

export function Assistant() {
  const { drafts, setDraft, notify } = useWorkspace()
  const composer = useMemo(
    () => (drafts.composer as Composer | undefined) ?? { text: '', files: [], key: '' },
    [drafts.composer],
  )
  const { data, error, refresh } = useResource<Page<WorkMessage>>('/messages', 2000)
  const [older, setOlder] = useState<WorkMessage[]>([])
  const [cursor, setCursor] = useState<string | null | undefined>(undefined)
  const [busy, setBusy] = useState(false)
  const [sendError, setSendError] = useState('')
  const [captureState, setCaptureState] = useState<CaptureState>('idle')
  const recording = captureState === 'recording'
  const capturing = captureState !== 'idle'
  const [seconds, setSeconds] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  const capture = useRef<AudioCapture | null>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const composerRef = useRef(composer)
  useEffect(() => {
    composerRef.current = composer
  }, [composer])
  const change = (next: Composer) =>
    setDraft(
      'composer',
      next.text || next.files.length || next.replyTo
        ? { ...next, key: next.key || crypto.randomUUID() }
        : undefined,
    )
  useEffect(() => {
    const controller = new AudioCapture({
      state: (state) => {
        setCaptureState(state)
        if (state === 'recording') setSeconds(0)
        setDraft('recording', state !== 'idle' ? true : undefined)
      },
      error: setSendError,
      file: (file) => {
        setDraft('composer', (previous: Composer | undefined) => appendRecordedFile(previous, file))
      },
    })
    capture.current = controller
    const guard = () => {
      if (document.hidden) controller.stop()
    }
    document.addEventListener('visibilitychange', guard)
    return () => {
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
    const limit = setTimeout(() => controller?.stop(), 180000)
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
    if (files.some((f) => !['image/jpeg', 'image/png', 'image/webp'].includes(f.type))) {
      setSendError('图片请使用 JPEG、PNG 或 WebP；语音请使用录音按钮或选择语音文件')
      return
    }
    if (
      existing.files.some((f) => f.file.type.startsWith('audio/')) ||
      files.length + existing.files.length > 4 ||
      files.some((f) => f.size > 5 * 1024 * 1024)
    ) {
      setSendError('每次最多 4 张图片，每张不超过 5 MiB；图片与语音请分开发送')
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
      setSendError('请先发送或移除已有附件')
      return
    }
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      setSendError('当前浏览器无法录音，请使用安全的 HTTPS 地址，或选择语音文件、输入文字')
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
    try {
      const files = [...composer.files]
      for (let i = 0; i < files.length; i++) {
        if (!files[i].attachment) {
          const form = new FormData()
          form.append('file', files[i].file)
          files[i] = {
            ...files[i],
            attachment: await api<Attachment>('/uploads', { method: 'POST', body: form }),
          }
        }
        current = { ...current, files }
        change(current)
      }
      await write(
        '/messages',
        {
          text: current.text,
          attachmentIds: files.map((f) => f.attachment!.id),
          replyTo: current.replyTo ?? null,
        },
        'POST',
        current.key,
      )
      files.forEach((f) => URL.revokeObjectURL(f.url))
      setDraft('composer', undefined)
      refresh()
      notify('已发送')
    } catch (e) {
      setSendError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const messages = [...older, ...(data?.items ?? [])]
    .filter((m, index, all) => all.findIndex((x) => x.id === m.id) === index)
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt))
  const nextCursor = cursor === undefined ? data?.nextCursor : cursor
  return (
    <div className="assistant-page">
      <div className="chat-scroll" ref={scroller}>
        <div className="chat-content">
          <ErrorNotice retry={refresh}>{error}</ErrorNotice>
          {nextCursor && (
            <button
              className="load-more"
              onClick={async () => {
                try {
                  const page = await api<Page<WorkMessage>>(`/messages?cursor=${nextCursor}`)
                  setOlder([...older, ...page.items])
                  setCursor(page.nextCursor)
                } catch (e) {
                  notify((e as Error).message)
                }
              }}
            >
              加载更早消息
            </button>
          )}
          {!messages.length && !error && (
            <Empty title="从今天的工作开始">
              发一段进展、现场图片或语音，工作助手会帮你整理。你确认后，再计入工作记录。
            </Empty>
          )}
          {messages.map((message) => (
            <MessageCard
              key={message.id}
              message={message}
              own
              onChange={refresh}
              onReply={() => {
                change({ ...composer, replyTo: message.id })
                input.current?.focus()
              }}
            />
          ))}
        </div>
      </div>
      <div className="composer-wrap">
        <div className="composer">
          <p className="visibility-note">发送后的工作消息及附件，老板／管理员可查看</p>
          {composer.replyTo && (
            <div className="replying">
              <CornerUpLeft size={14} />
              正在补充此前消息
              <button
                className="icon-button"
                aria-label="取消补充关联"
                onClick={() => change({ ...composer, replyTo: undefined })}
              >
                <X size={14} />
              </button>
            </div>
          )}
          {composer.files.length > 0 && (
            <div className="attachments pending">
              {composer.files.map((item) => (
                <div key={item.id}>
                  {item.file.type.startsWith('image/') ? (
                    <img src={item.url} alt={item.file.name} />
                  ) : (
                    <audio controls src={item.url} preload="metadata" />
                  )}
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
            aria-label="工作消息"
            placeholder="今天有什么进展？也可以随时补充一条消息…"
            rows={3}
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
                title="最多4张，每张5MiB，JPEG/PNG/WebP"
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
                  title="最长3分钟"
                  aria-label="录制语音"
                  disabled={busy}
                  onClick={startRecording}
                >
                  <Mic size={20} />
                </button>
              )}
              <label className="file-label">
                语音文件
                <input
                  type="file"
                  accept="audio/webm,audio/mp4,audio/aac,audio/wav,.m4a"
                  hidden
                  disabled={busy || capturing}
                  onChange={(e) => {
                    const file = e.target.files?.[0]
                    if (!file) return
                    if (composer.files.length || file.size > 20 * 1024 * 1024) {
                      setSendError('每次一段语音，最长3分钟、20MiB，请先移除其他附件')
                      return
                    }
                    change({
                      ...composer,
                      key: '',
                      files: [{ id: crypto.randomUUID(), file, url: URL.createObjectURL(file) }],
                    })
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
          <small>图片最多 4 张／每张 5 MiB；语音最长 3 分钟／20 MiB。</small>
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
  const [editing, setEditing] = useState<Draft | null>(null)
  const [transcript, setTranscript] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const { notify } = useWorkspace()
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
        <span className="eyebrow">工作上报</span>
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
      {message.job && <JobNotice job={message.job} refresh={onChange} />}
      {message.reply && (
        <div className="assistant-reply">
          <h3>
            <Sparkles size={16} />
            工作助手
          </h3>
          <p className="preserve">{message.reply}</p>
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
              {d.status === 'pending' && (
                <div className="card-actions">
                  <button
                    className="primary small"
                    disabled={busy}
                    onClick={() => void act([d], 'confirm')}
                  >
                    <Check size={15} />
                    确认进展
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
                  <Link to={`/messages/${message.id}`}>查看来源</Link>
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
              <small>此处展示助手当时提出的原始建议；已确认内容以工作进展为准。</small>
            </div>
          ))}
      {pending.length > 1 && (
        <button disabled={busy} onClick={() => void act(pending, 'confirm')}>
          确认本轮 {pending.length} 项进展
        </button>
      )}
      <ErrorNotice>{error}</ErrorNotice>
      {editing && (
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
            <textarea
              name="text"
              rows={8}
              defaultValue={message.transcript}
              maxLength={8000}
              required
            />
            <p className="muted">保留原录音；新文字用于之后的处理。已有进展不会被自动修改。</p>
            <BusyButton busy={busy} className="primary">
              保存修正
            </BusyButton>
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
  if (job.state === 'succeeded') return null
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
        <textarea
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
        <textarea
          rows={2}
          value={value.blocker}
          maxLength={2000}
          onChange={(e) => change({ ...value, blocker: e.target.value })}
        />
      </label>
      <label>
        下一步
        <textarea
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
        <p className="muted">编辑内容仅自己可见；确认后才更新工作记录。</p>
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
  const navigate = useNavigate()
  return (
    <div className="page narrow">
      <button className="text-button" onClick={() => navigate(-1)}>
        ← 返回之前页面
      </button>
      <h2>原始上报</h2>
      <ErrorNotice retry={refresh}>{error}</ErrorNotice>
      {data && (
        <MessageCard message={data} own={data.ownerId === identity.member.id} onChange={refresh} />
      )}
    </div>
  )
}
