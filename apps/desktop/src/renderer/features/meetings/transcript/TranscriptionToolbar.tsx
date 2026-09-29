import type { TranscriptionStatus } from '../../../../shared/contracts'
import { languageNames } from '../../settings/models/LocalModelSettings'

export const time = (milliseconds: number): string => {
  const seconds = Math.floor(milliseconds / 1000)
  return `${Math.floor(seconds / 60)
    .toString()
    .padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`
}
const states: Record<TranscriptionStatus['state'], string> = {
  not_started: '尚未转写',
  queued: '等待处理',
  running: '正在转写',
  draining: '正在补齐文字',
  completed: '转写完成',
  paused: '转写已暂停',
  failed: '转写失败',
}
export function TranscriptionToolbar({
  live,
  locating,
  status,
  viewMode,
  onViewMode,
  copying,
  canCopy,
  onCopy,
  copyMessage,
}: {
  live: boolean
  locating: boolean
  status: TranscriptionStatus | null
  viewMode: 'speakers' | 'text'
  onViewMode: (mode: 'speakers' | 'text') => void
  copying: boolean
  canCopy: boolean
  onCopy: () => void
  copyMessage: string
}): React.JSX.Element {
  const active = status && ['queued', 'running', 'draining'].includes(status.state)
  const progress = status
    ? `已处理 ${time(status.processedMs)} / 录音 ${time(status.audioMs)}${status.pendingMs > 0 && status.state !== 'not_started' ? ` · 待处理 ${time(status.pendingMs)}` : ''}`
    : ''
  return (
    <div className="transcription-toolbar">
      <div className="transcript-view-toolbar">
        {live && <strong>实时文字</strong>}
        <div className="view-switch" role="group" aria-label="文字记录视图">
          {(['speakers', 'text'] as const).map((mode) => (
            <button key={mode} aria-pressed={viewMode === mode} onClick={() => onViewMode(mode)}>
              {mode === 'speakers' ? '按发言人' : '纯文本'}
            </button>
          ))}
        </div>
        <span role="status" className="transcript-state">
          {locating
            ? '正在定位引用…'
            : status
              ? `${status.candidate ? '重新转写 · ' : ''}${states[status.state]}`
              : '正在读取文字'}
        </span>
        <button
          className="text-button"
          disabled={copying || !canCopy}
          onClick={onCopy}
          title={
            viewMode === 'speakers'
              ? '复制完整文字，包含发言人和时间戳'
              : '复制完整文字，仅包含文字和时间戳'
          }
        >
          {copying ? '正在复制…' : '复制文字'}
        </button>
        {status && (
          <details className="transcription-details">
            <summary>处理信息</summary>
            <div>
              {status.published && (
                <p className="transcript-configuration">
                  当前文字：
                  {status.published.modelId
                    .split('/')
                    .at(-1)
                    ?.replace(/^(?:faster-)?whisper-/, 'Whisper ')
                    .replace(/-mlx$/, '')}
                  {' · '}
                  {languageNames[status.published.language]}
                  {' · '}
                  {(status.published.device ?? 'cpu').toUpperCase()}
                </p>
              )}
              {status.actual && (!status.published || status.candidate) && (
                <p className="transcript-configuration">
                  {status.candidate ? '本次重新转写' : '本次转写'}：
                  {status.actual.modelId
                    .split('/')
                    .at(-1)
                    ?.replace(/^(?:faster-)?whisper-/, 'Whisper ')
                    .replace(/-mlx$/, '')}
                  {' · '}
                  {languageNames[status.actual.language]}
                  {' · '}
                  {(status.actual.device ?? 'cpu').toUpperCase()}
                </p>
              )}
              {!active && <p className="transcript-progress">{progress}</p>}
            </div>
          </details>
        )}
      </div>
      {active && (
        <p className="transcript-progress" role="status">
          {progress}
        </p>
      )}
      {copyMessage && <small role="status">{copyMessage}</small>}
    </div>
  )
}
