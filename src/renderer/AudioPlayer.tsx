import {
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type Ref,
  type KeyboardEvent,
} from 'react'
import { Pause, Play, RotateCcw, RotateCw, Volume2, VolumeX } from 'lucide-react'

export type AudioPlayerHandle = { pause(): void; seek(milliseconds: number): void }
export function audioTime(seconds: number): string {
  const whole = Math.max(0, Math.floor(Number.isFinite(seconds) ? seconds : 0))
  const minutes = Math.floor(whole / 60)
  return whole >= 3600
    ? `${Math.floor(whole / 3600)}:${String(minutes % 60).padStart(2, '0')}:${String(whole % 60).padStart(2, '0')}`
    : `${String(minutes).padStart(2, '0')}:${String(whole % 60).padStart(2, '0')}`
}
export function AudioPlayer({
  meetingId,
  durationMs,
  enabled = true,
  ref,
}: {
  meetingId: string
  durationMs: number
  enabled?: boolean
  ref?: Ref<AudioPlayerHandle>
}): React.JSX.Element {
  const audio = useRef<HTMLAudioElement>(null)
  const alive = useRef(true)
  const pendingSeek = useRef<number | null>(null)
  const [playing, setPlaying] = useState(false)
  const [ready, setReady] = useState(false)
  const [waiting, setWaiting] = useState(false)
  const [ended, setEnded] = useState(false)
  const [position, setPosition] = useState(0)
  const [length, setLength] = useState(durationMs / 1000)
  const [rate, setRate] = useState(1)
  const [volume, setVolume] = useState(1)
  const [muted, setMuted] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    alive.current = true
    const element = audio.current
    return () => {
      alive.current = false
      element?.pause()
    }
  }, [])
  useEffect(() => {
    if (!enabled) audio.current?.pause()
  }, [enabled])
  function play(): void {
    if (!enabled) return
    const element = audio.current
    if (!element) return
    setError('')
    void element.play().catch(() => {
      if (alive.current) {
        setWaiting(false)
        setError('无法播放录音，请重试；若仍失败，请检查音频文件。')
      }
    })
  }
  function seek(seconds: number, start = false): void {
    if (!enabled) return
    const element = audio.current
    if (!element) return
    const end = Number.isFinite(element.duration) ? element.duration : durationMs / 1000
    const target = Math.max(0, Math.min(end, seconds))
    if (element.readyState === 0) pendingSeek.current = target
    else {
      element.currentTime = target
      setPosition(target)
    }
    setEnded(false)
    if (start) play()
  }
  useImperativeHandle(ref, () => ({
    pause: () => audio.current?.pause(),
    seek: (ms) => seek(ms / 1000, true),
  }))
  function toggle(): void {
    if (!audio.current) return
    if (audio.current.paused) play()
    else audio.current.pause()
  }
  function setAudioVolume(value: number): void {
    if (!audio.current) return
    audio.current.volume = Math.max(0, Math.min(1, value))
    if (value > 0) audio.current.muted = false
  }
  function keyboard(event: KeyboardEvent<HTMLElement>): void {
    if (!enabled) return
    const target = event.target as HTMLElement
    if (
      target.closest('input, select, textarea, button, [contenteditable="true"]') ||
      event.altKey ||
      event.metaKey ||
      event.ctrlKey
    )
      return
    const element = audio.current
    if (!element) return
    switch (event.key.toLowerCase()) {
      case ' ':
      case 'k':
        toggle()
        break
      case 'arrowleft':
      case 'j':
        seek(element.currentTime - 10)
        break
      case 'arrowright':
      case 'l':
        seek(element.currentTime + 10)
        break
      case 'arrowup':
        setAudioVolume(element.volume + 0.1)
        break
      case 'arrowdown':
        setAudioVolume(element.volume - 0.1)
        break
      case 'm':
        element.muted = !element.muted
        break
      default:
        return
    }
    event.preventDefault()
  }
  return (
    <section
      className="audio-player"
      aria-label="会议录音播放器"
      tabIndex={enabled ? 0 : -1}
      onKeyDown={keyboard}
    >
      <audio
        ref={audio}
        preload="metadata"
        src={`paa-audio://meeting/${meetingId}`}
        onLoadedMetadata={() => {
          const element = audio.current
          if (!element) return
          if (Number.isFinite(element.duration)) setLength(element.duration)
          setReady(true)
          if (pendingSeek.current !== null) {
            seek(pendingSeek.current)
            pendingSeek.current = null
          }
        }}
        onDurationChange={() => {
          if (audio.current && Number.isFinite(audio.current.duration))
            setLength(audio.current.duration)
        }}
        onTimeUpdate={() => setPosition(audio.current?.currentTime ?? 0)}
        onPlay={() => {
          setPlaying(true)
          setEnded(false)
        }}
        onPlaying={() => setWaiting(false)}
        onPause={() => {
          setPlaying(false)
          setWaiting(false)
        }}
        onWaiting={() => setWaiting(true)}
        onCanPlay={() => setWaiting(false)}
        onEnded={() => {
          setPlaying(false)
          setEnded(true)
          setWaiting(false)
        }}
        onRateChange={() => setRate(audio.current?.playbackRate ?? 1)}
        onVolumeChange={() => {
          setVolume(audio.current?.volume ?? 1)
          setMuted(audio.current?.muted ?? false)
        }}
        onError={() => {
          setWaiting(false)
          setError('音频文件无法读取，请检查文件是否缺失或损坏。')
        }}
      />
      <fieldset disabled={!enabled} className="player-fields">
        <div className="player-timeline">
          <output aria-label="播放时间">{audioTime(position)}</output>
          <input
            type="range"
            min={0}
            max={Math.max(length, 0.01)}
            step={0.1}
            value={Math.min(position, length)}
            disabled={!ready || !!error}
            aria-label="播放进度"
            aria-valuetext={`${audioTime(position)} / ${audioTime(length)}`}
            onChange={(event) => seek(Number(event.target.value))}
          />
          <span aria-label="总时长">{audioTime(length)}</span>
        </div>
        <div className="player-controls">
          <button
            className="player-icon"
            aria-label="后退 10 秒"
            disabled={!ready || !!error}
            onClick={() => seek((audio.current?.currentTime ?? 0) - 10)}
          >
            <RotateCcw size={19} />
            <span>10</span>
          </button>
          <button
            className="player-play"
            aria-label={playing ? '暂停播放' : '播放录音'}
            onClick={toggle}
          >
            {playing ? <Pause size={21} /> : <Play size={21} />}
          </button>
          <button
            className="player-icon"
            aria-label="前进 10 秒"
            disabled={!ready || !!error}
            onClick={() => seek((audio.current?.currentTime ?? 0) + 10)}
          >
            <RotateCw size={19} />
            <span>10</span>
          </button>
          <label className="player-speed">
            倍速
            <select
              aria-label="播放倍速"
              value={rate}
              onChange={(event) => {
                if (audio.current) {
                  audio.current.preservesPitch = true
                  audio.current.playbackRate = Number(event.target.value)
                }
              }}
            >
              {[0.5, 0.75, 1, 1.25, 1.5, 2].map((value) => (
                <option key={value} value={value}>
                  {value}×
                </option>
              ))}
            </select>
          </label>
          <div className="player-volume">
            <button
              className="player-icon"
              aria-label={muted ? '取消静音' : '静音'}
              onClick={() => {
                if (audio.current) audio.current.muted = !audio.current.muted
              }}
            >
              {muted || !volume ? <VolumeX size={20} /> : <Volume2 size={20} />}
            </button>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={muted ? 0 : volume}
              aria-label="播放音量"
              onChange={(event) => setAudioVolume(Number(event.target.value))}
            />
          </div>
        </div>
      </fieldset>
      <p className="player-status" role={error ? 'alert' : 'status'}>
        {(!enabled ? '录音或重新连接期间暂停回放。' : '') ||
          error ||
          (waiting ? '正在缓冲…' : !ready ? '正在读取录音…' : ended ? '播放结束' : '\u00a0')}
      </p>
      <details className="player-shortcuts">
        <summary>快捷键</summary>
        <p>
          播放器获得焦点后：空格 / K 播放或暂停，← / J 后退 10 秒，→ / L 前进 10 秒，↑ / ↓
          调节音量，M 静音。进度条获得焦点后可用方向键微调。
        </p>
      </details>
    </section>
  )
}
