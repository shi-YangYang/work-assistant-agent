import { useEffect, useRef, useState } from 'react'
import { Users, Pencil } from 'lucide-react'
import type { SpeakerRequest, SpeakerStatus } from '../shared/speaker-contracts'
import type { TranscriptSegment } from '../shared/contracts'

export function SpeakerPanel({
  status,
  segment,
  onCloseSegment,
  connected,
}: {
  status: SpeakerStatus | null
  segment: TranscriptSegment | null
  onCloseSegment: () => void
  connected: boolean
}): React.JSX.Element | null {
  const [mode, setMode] = useState<'name' | 'segment' | null>(segment ? 'segment' : null)
  const [speakerId, setSpeakerId] = useState(segment?.speaker ?? '')
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const dialog = useRef<HTMLDialogElement>(null)
  const generation = useRef(status?.generation ?? '')
  const revision = useRef(status?.revision ?? 0)
  useEffect(() => {
    if (mode) dialog.current?.showModal()
  }, [mode])
  if (!status) return null
  const current = status
  const running = current.state === 'running'
  function close(): void {
    dialog.current?.close()
    setMode(null)
    setError('')
    onCloseSegment()
  }
  async function request(input: SpeakerRequest, dismiss = false): Promise<void> {
    setBusy(true)
    setError('')
    try {
      const result = await window.paa.speakers(input)
      if (!result.ok) setError(result.message)
      else if (dismiss) close()
    } catch {
      setError('请求未确认，请查看处理状态后重试。')
    } finally {
      setBusy(false)
    }
  }
  function rename(id: string, value: string): void {
    setSpeakerId(id)
    setName(value)
    generation.current = current.generation
    revision.current = current.revision
    setError('')
    setMode('name')
  }
  return (
    <div className="speaker-panel">
      <div className="speaker-toolbar">
        <span className="speaker-title">
          <Users size={15} />
          说话人
        </span>
        {current.state === 'completed' ? (
          <span className="speaker-device">
            {current.speakers.length} 位 ·{' '}
            {current.device === 'mps'
              ? 'Apple GPU'
              : current.device === 'cuda'
                ? 'NVIDIA GPU'
                : 'CPU'}
          </span>
        ) : (
          <span className="speaker-device" role="status">
            {running ? current.progress || '正在准备…' : current.state === 'paused' ? '已暂停' : ''}
          </span>
        )}
        <div className="speaker-toolbar-actions">
          {running ? (
            <button
              className="text-button"
              disabled={busy || !connected}
              onClick={() => void request({ action: 'cancel', meetingId: current.meetingId })}
            >
              取消
            </button>
          ) : (
            current.state !== 'completed' && (
              <button
                className="secondary-button"
                disabled={busy || !connected || current.model.state !== 'ready'}
                onClick={() => void request({ action: 'start', meetingId: current.meetingId })}
              >
                {current.state === 'paused' || current.state === 'failed'
                  ? '重新区分说话人'
                  : '区分说话人'}
              </button>
            )
          )}
        </div>
      </div>
      {!!current.speakers.length && (
        <div className="speaker-chips" aria-label="本场会议说话人">
          {current.speakers.map((speaker) => (
            <button
              key={speaker.id}
              disabled={!connected}
              onClick={() => rename(speaker.id, speaker.name)}
              title="修改本场会议中的姓名"
            >
              <span>{speaker.name}</span>
              <Pencil size={12} />
            </button>
          ))}
        </div>
      )}
      {(error || current.error || current.model.error) && !mode && (
        <p className="audio-warning" role="alert">
          {error || current.error || current.model.error}
        </p>
      )}
      {mode && (
        <dialog
          ref={dialog}
          className="library-dialog speaker-dialog"
          onCancel={(event) => {
            event.preventDefault()
            close()
          }}
        >
          <form
            onSubmit={(event) => {
              event.preventDefault()
              const base = {
                meetingId: current.meetingId,
                generation: generation.current,
                revision: revision.current,
              }
              if (mode === 'name')
                void request({ action: 'rename', ...base, speakerId, name }, true)
              else if (mode === 'segment' && segment)
                void request(
                  {
                    action: 'assign',
                    ...base,
                    segmentId: segment.id,
                    speakerId: speakerId || null,
                  },
                  true,
                )
            }}
          >
            <h2>{mode === 'name' ? '修改说话人姓名' : '调整这段发言'}</h2>
            {mode === 'name' ? (
              <label>
                本场会议中的姓名
                <input
                  autoFocus
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  maxLength={40}
                  required
                />
              </label>
            ) : (
              <>
                <p className="speaker-excerpt">{segment?.text}</p>
                <label>
                  说话人
                  <select
                    value={speakerId}
                    onChange={(event) => setSpeakerId(event.target.value)}
                    autoFocus
                  >
                    <option value="">多人／待确认</option>
                    {current.speakers.map((speaker) => (
                      <option key={speaker.id} value={speaker.id}>
                        {speaker.name}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            )}
            {error && (
              <p className="audio-warning" role="alert">
                {error}
              </p>
            )}
            <div className="dialog-actions">
              <button type="button" className="secondary-button" onClick={close}>
                取消
              </button>
              <button
                className="primary-button"
                disabled={busy || !connected || (mode === 'name' && !name.trim())}
              >
                保存
              </button>
            </div>
          </form>
        </dialog>
      )}
    </div>
  )
}
