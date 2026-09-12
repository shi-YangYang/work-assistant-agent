import { useEffect, useRef, useState } from 'react'
import { MoreHorizontal } from 'lucide-react'
import { ACTIVE_STATES, type Meeting } from '../shared/contracts'
import type { ExportOptions } from '../shared/library-contracts'

export function MeetingActions({
  meeting,
  visible = true,
  detail = false,
  onChanged,
  onDeleted,
  beforeDelete,
  summaryAvailable,
}: {
  meeting: Meeting
  visible?: boolean
  detail?: boolean
  onChanged: (meeting: Meeting) => void
  onDeleted: (id: string) => void
  beforeDelete?: () => void
  summaryAvailable?: boolean
}): React.JSX.Element {
  const [mode, setMode] = useState<'rename' | 'delete' | 'export' | null>(null)
  const [title, setTitle] = useState(meeting.title)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [available, setAvailable] = useState({
    summary: false,
    transcript: false,
    incomplete: false,
    deletingBusy: '',
  })
  const [options, setOptions] = useState<ExportOptions>({
    format: 'md',
    scope: 'summary',
    timestamps: true,
  })
  const dialog = useRef<HTMLDialogElement>(null)
  const menu = useRef<HTMLDetailsElement>(null)
  const trigger = useRef<HTMLElement | null>(null)
  useEffect(() => {
    if (!visible) {
      dialog.current?.close()
      if (menu.current) menu.current.open = false
    }
  }, [visible])
  useEffect(() => {
    if (!mode && !detail) return
    if (mode) dialog.current?.showModal()
    let alive = true
    void Promise.all([
      window.paa.getSummary(meeting.id),
      window.paa.getTranscriptionStatus(meeting.id),
      window.paa.listTranscript(meeting.id),
    ])
      .then(([summary, transcription, transcript]) => {
        if (!alive) return
        setAvailable({
          summary: !!(summary.ok && summary.value.result),
          transcript: !!(transcript.ok && transcript.value.segments.length),
          incomplete:
            meeting.status !== 'completed' ||
            !transcription.ok ||
            transcription.value.state !== 'completed',
          deletingBusy:
            transcription.ok &&
            ['queued', 'running', 'draining'].includes(transcription.value.state)
              ? '这场会议正在转写，请完成后再删除。'
              : summary.ok &&
                  summary.value.task &&
                  ['queued', 'running'].includes(summary.value.task.state)
                ? '这场会议正在生成纪要，请完成后再删除。'
                : '',
        })
      })
      .catch(() => {
        if (alive) setError('无法读取资料状态，请重试。')
      })
    return () => {
      alive = false
    }
  }, [mode, detail, meeting.id, meeting.status])
  function close(): void {
    if (busy) return
    dialog.current?.close()
    setMode(null)
    trigger.current?.focus()
  }
  function show(next: NonNullable<typeof mode>): void {
    trigger.current = document.activeElement as HTMLElement
    if (menu.current) menu.current.open = false
    setTitle(meeting.title)
    setError('')
    setMessage('')
    setMode(next)
  }
  async function act(): Promise<void> {
    setBusy(true)
    setError('')
    setMessage('')
    try {
      if (mode === 'rename') {
        const response = await window.paa.renameMeeting(meeting.id, title)
        if (!response.ok) throw new Error(response.message)
        onChanged(response.value)
      } else if (mode === 'delete') {
        beforeDelete?.()
        const response = await window.paa.deleteMeeting(meeting.id)
        if (!response.ok) {
          const current = await window.paa.getMeeting(meeting.id)
          if (current.ok) onChanged(current.value)
          throw new Error(response.message)
        }
        onDeleted(meeting.id)
      } else if (mode === 'export') {
        const response = await window.paa.exportMeeting(meeting.id, options)
        if (!response.ok) throw new Error(response.message)
        if (response.value.canceled) return
        setMessage('会议已导出。')
      }
      dialog.current?.close()
      setMode(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '操作失败，请重试。')
    } finally {
      setBusy(false)
    }
  }
  async function copy(): Promise<void> {
    setBusy(true)
    setMessage('')
    setError('')
    try {
      const response = await window.paa.copyMinutes(meeting.id)
      if (!response.ok) throw new Error(response.message)
      setMessage('纪要已复制。')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '复制失败，请重试。')
    } finally {
      setBusy(false)
    }
  }
  const active = ACTIVE_STATES.includes(meeting.status)
  return (
    <div className="meeting-actions" onClick={(event) => event.stopPropagation()}>
      {detail && !meeting.deleting && (
        <>
          <button
            className="secondary-button"
            disabled={active || busy || !(summaryAvailable ?? available.summary)}
            onClick={() => void copy()}
          >
            复制纪要
          </button>
          <button
            className="secondary-button"
            disabled={active || busy}
            onClick={() => show('export')}
          >
            导出
          </button>
        </>
      )}
      <details
        ref={menu}
        className="meeting-menu"
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.currentTarget.open = false
            event.currentTarget.querySelector('summary')?.focus()
          }
        }}
      >
        <summary aria-label={`${meeting.title}的操作`}>
          <MoreHorizontal size={19} />
        </summary>
        <div className="meeting-menu-items">
          <button disabled={active || !!meeting.deleting} onClick={() => show('rename')}>
            重命名
          </button>
          <button className="danger-text" disabled={active} onClick={() => show('delete')}>
            {meeting.deleting ? '重试删除' : '删除会议'}
          </button>
          {active && <small>录音保存后可操作</small>}
        </div>
      </details>
      {message && <small role="status">{message}</small>}
      {error && !mode && <small role="alert">{error}</small>}
      {mode && (
        <dialog
          ref={dialog}
          onClose={() => {
            setMode(null)
            trigger.current?.focus()
          }}
          className="library-dialog"
          onCancel={(event) => {
            event.preventDefault()
            close()
          }}
          aria-label={
            mode === 'rename' ? '重命名会议' : mode === 'delete' ? '删除会议' : '导出会议'
          }
        >
          <form
            onSubmit={(event) => {
              event.preventDefault()
              void act()
            }}
          >
            <h2>
              {mode === 'rename' ? '重命名会议' : mode === 'delete' ? '删除会议' : '导出会议'}
            </h2>
            {mode === 'rename' && (
              <label>
                会议名称
                <input
                  autoFocus
                  value={title}
                  maxLength={200}
                  onChange={(event) => setTitle(event.target.value)}
                />
              </label>
            )}
            {mode === 'delete' && (
              <>
                <p>确定永久删除「{meeting.title}」？</p>
                <p>关联音频、文字记录和纪要将一起删除，应用内无法恢复。已导出的文件不受影响。</p>
                {available.deletingBusy && <p role="alert">{available.deletingBusy}</p>}
                {meeting.deletionError && <p>{meeting.deletionError}</p>}
              </>
            )}
            {mode === 'export' && (
              <>
                <label>
                  文件格式
                  <select
                    value={options.format}
                    onChange={(event) =>
                      setOptions({
                        ...options,
                        format: event.target.value as ExportOptions['format'],
                      })
                    }
                  >
                    <option value="md">Markdown (.md)</option>
                    <option value="txt">纯文本 (.txt)</option>
                  </select>
                </label>
                <label>
                  导出内容
                  <select
                    value={options.scope}
                    onChange={(event) =>
                      setOptions({
                        ...options,
                        scope: event.target.value as ExportOptions['scope'],
                      })
                    }
                  >
                    <option value="summary" disabled={!available.summary}>
                      会议纪要{!available.summary ? '（尚未生成）' : ''}
                    </option>
                    <option value="transcript" disabled={!available.transcript}>
                      文字记录{!available.transcript ? '（暂无文字）' : ''}
                    </option>
                    <option value="both" disabled={!available.summary || !available.transcript}>
                      纪要和文字记录
                    </option>
                  </select>
                </label>
                {options.scope !== 'summary' && (
                  <label className="check-label">
                    <input
                      type="checkbox"
                      checked={options.timestamps}
                      onChange={(event) =>
                        setOptions({ ...options, timestamps: event.target.checked })
                      }
                    />
                    包含时间戳
                  </label>
                )}
                {available.incomplete && (
                  <p className="audio-warning">资料尚不完整，本次仅导出已保存的内容。</p>
                )}
              </>
            )}
            {error && (
              <p role="alert" className="audio-warning">
                {error}
              </p>
            )}
            <div className="button-row">
              <button type="button" className="secondary-button" disabled={busy} onClick={close}>
                取消
              </button>
              <button
                className={mode === 'delete' ? 'primary-button delete-button' : 'primary-button'}
                disabled={
                  busy ||
                  (mode === 'delete' && !!available.deletingBusy) ||
                  (mode === 'export' &&
                    ((options.scope !== 'transcript' && !available.summary) ||
                      (options.scope !== 'summary' && !available.transcript)))
                }
              >
                {busy
                  ? '处理中…'
                  : mode === 'rename'
                    ? '保存'
                    : mode === 'delete'
                      ? '永久删除'
                      : '选择保存位置'}
              </button>
            </div>
          </form>
        </dialog>
      )}
    </div>
  )
}
