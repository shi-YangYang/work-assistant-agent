import { useEffect, useState } from 'react'
import { AudioLines, Upload, RefreshCw, Trash2, CheckCircle2, CircleUserRound } from 'lucide-react'
import { api, dateLabel, useResource, write } from './api'
import { BusyButton, ErrorNotice, Modal } from './ui'

type Enrollment = {
  memberId: string
  name: string
  role: string
  active: boolean
  state: 'empty' | 'queued' | 'processing' | 'ready' | 'failed' | 'incompatible'
  revision: number
  ready: boolean
  filename: string
  error: string
  speechSeconds: number
  updatedAt: string | null
}
type VoiceprintList = { modelId: string; items: Enrollment[]; limit: number }
const status = {
  empty: '未登记',
  queued: '等待处理',
  processing: '正在提取',
  ready: '已就绪',
  failed: '登记失败',
  incompatible: '需要重新登记',
}

export function VoiceprintsPage() {
  const resource = useResource<VoiceprintList>('/settings/voiceprints')
  const processing = !!resource.data?.items.some(
    (v) => v.state === 'queued' || v.state === 'processing',
  )
  const { refresh, error: loadError } = resource
  const [selected, setSelected] = useState<Enrollment | null>(null)
  const [error, setError] = useState<Error | string>('')
  const [busy, setBusy] = useState('')
  const [search, setSearch] = useState('')
  useEffect(() => {
    if (!processing || loadError) return
    const timer = window.setInterval(() => {
      if (!document.hidden) refresh()
    }, 3000)
    return () => window.clearInterval(timer)
  }, [processing, loadError, refresh])
  const items =
    resource.data?.items.filter((v) =>
      v.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()),
    ) ?? []
  const act = async (item: Enrollment, action: 'retry' | 'delete') => {
    if (
      action === 'delete' &&
      !window.confirm(`删除 ${item.name} 的声纹及登记录音？已下载到离线桌面的副本不会被移除。`)
    )
      return
    setBusy(item.memberId)
    setError('')
    try {
      await write(
        `/settings/voiceprints/${item.memberId}${action === 'retry' ? '/retry' : ''}`,
        {},
        action === 'retry' ? 'POST' : 'DELETE',
      )
      resource.refresh()
    } catch (e) {
      setError(e as Error)
    } finally {
      setBusy('')
    }
  }
  return (
    <div className="settings-page voiceprints-page">
      <header className="voiceprint-heading">
        <div>
          <h2>公司声纹</h2>
          <p className="muted">登记成员的声音，让桌面会议助手识别发言者。</p>
        </div>
        <button onClick={resource.refresh} aria-label="刷新声纹">
          <RefreshCw size={16} />
          刷新
        </button>
      </header>
      <ErrorNotice retry={resource.refresh}>{resource.error || error}</ErrorNotice>
      <section className="panel voiceprint-library">
        <div className="voiceprint-toolbar">
          <span>
            <AudioLines size={18} /> {resource.data?.items.filter((v) => v.ready).length ?? 0}{' '}
            位成员已登记
          </span>
          <input
            type="search"
            aria-label="搜索声纹成员"
            placeholder="搜索成员"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="voiceprint-list">
          {items.map((item) => {
            const processing = ['queued', 'processing'].includes(item.state)
            return (
              <article key={item.memberId} className="voiceprint-member">
                <span className="voiceprint-avatar">
                  <CircleUserRound size={24} />
                </span>
                <div className="voiceprint-member-info">
                  <strong>
                    {item.name}
                    {item.role === 'admin' && <small>管理员</small>}
                  </strong>
                  <span className={`voiceprint-status ${item.ready ? 'ready' : ''}`}>
                    {item.ready && <CheckCircle2 size={14} />}
                    {item.active ? status[item.state] : '成员已停用'}
                    {item.ready && item.state !== 'ready' ? ' · 原声纹仍可用' : ''}
                  </span>
                  {item.updatedAt && (
                    <small>
                      {dateLabel(item.updatedAt)}
                      {item.speechSeconds > 0 ? ` · 有效声音 ${item.speechSeconds} 秒` : ''}
                    </small>
                  )}
                  {item.error && <p className="voiceprint-error">{item.error}</p>}
                </div>
                <div className="voiceprint-actions">
                  {item.state === 'failed' && (
                    <button
                      disabled={busy === item.memberId}
                      onClick={() => void act(item, 'retry')}
                    >
                      <RefreshCw size={15} />
                      重试
                    </button>
                  )}
                  <button
                    disabled={!item.active || processing || busy === item.memberId}
                    onClick={() => setSelected(item)}
                  >
                    <Upload size={15} />
                    {item.ready ? '替换录音' : '上传录音'}
                  </button>
                  {item.state !== 'empty' && (
                    <button
                      className="icon-button"
                      aria-label={`删除 ${item.name} 的声纹`}
                      disabled={busy === item.memberId}
                      onClick={() => void act(item, 'delete')}
                    >
                      <Trash2 size={16} />
                    </button>
                  )}
                </div>
              </article>
            )
          })}
          {!items.length && (
            <p className="muted voiceprint-empty">
              {resource.data ? '没有匹配的成员' : '正在读取成员…'}
            </p>
          )}
        </div>
      </section>
      {selected && (
        <EnrollmentForm
          item={selected}
          onClose={() => setSelected(null)}
          onSaved={() => {
            setSelected(null)
            resource.refresh()
          }}
        />
      )}
    </div>
  )
}

function EnrollmentForm({
  item,
  onClose,
  onSaved,
}: {
  item: Enrollment
  onClose: () => void
  onSaved: () => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  return (
    <Modal
      title={`登记 ${item.name} 的声音`}
      onClose={() => {
        if (!busy) onClose()
      }}
    >
      <form
        className="voiceprint-enroll"
        onSubmit={async (e) => {
          e.preventDefault()
          if (!file || !consent) return
          if (file.size > 20 * 1024 * 1024) {
            setError('录音不能超过 20 MiB')
            return
          }
          const form = new FormData()
          form.set('file', file)
          form.set('consent', 'true')
          form.set('expectedRevision', String(item.revision))
          setBusy(true)
          setError('')
          try {
            await api(`/settings/voiceprints/${item.memberId}`, { method: 'POST', body: form })
            onSaved()
          } catch (err) {
            setError(err as Error)
          } finally {
            setBusy(false)
          }
        }}
      >
        <p>选择一段清晰的单人录音，中英文均可。建议 30～120 秒，避免背景音乐和其他人的声音。</p>
        <label>
          登记录音
          <input
            type="file"
            accept="audio/wav,audio/mpeg,audio/mp4,audio/aac,audio/webm,.wav,.mp3,.m4a,.aac,.webm"
            disabled={busy}
            required
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <small className="muted">最长 3 分钟，最大 20 MiB。替换处理成功前保留原声纹。</small>
        <label className="check">
          <input
            type="checkbox"
            checked={consent}
            disabled={busy}
            onChange={(e) => setConsent(e.target.checked)}
          />
          我已取得本人知情同意，授权用于公司会议发言者识别
        </label>
        <ErrorNotice>{error}</ErrorNotice>
        <div className="form-actions">
          <button type="button" disabled={busy} onClick={onClose}>
            取消
          </button>
          <BusyButton className="primary" busy={busy} disabled={!file || !consent}>
            上传并提取声纹
          </BusyButton>
        </div>
      </form>
    </Modal>
  )
}
