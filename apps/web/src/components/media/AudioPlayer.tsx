import { LoaderCircle, Pause, Play } from 'lucide-react'
import { useEffect, useRef, useState, type CSSProperties } from 'react'
import styles from './AudioPlayer.module.css'

type Props = {
  src: string
  name: string
  duration?: number | null
  label?: string
  suspended?: boolean
}

// Only custom players participate; draft previews and other media keep their own controls.
let activePlayer: { element: HTMLAudioElement; stop: () => void } | undefined

function finiteTime(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null
}

function timeLabel(value: number | null) {
  if (value === null) return '--:--'
  const seconds = Math.floor(value)
  const minutes = Math.floor(seconds / 60)
  return minutes >= 60
    ? `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
    : `${minutes}:${String(seconds % 60).padStart(2, '0')}`
}

export function AudioPlayer(props: Props) {
  // A real source change resets playback, but refreshed attachment objects do not.
  return <Playback key={props.src} {...props} />
}

function Playback({ src, name, duration: initialDuration, label, suspended = false }: Props) {
  const audio = useRef<HTMLAudioElement>(null)
  const requested = useRef(false)
  const attempt = useRef(0)
  const [playing, setPlaying] = useState(false)
  const [waiting, setWaiting] = useState(false)
  const [position, setPosition] = useState(0)
  const [mediaDuration, setMediaDuration] = useState<number | null>(null)
  const [seekable, setSeekable] = useState(false)
  const [error, setError] = useState('')
  const duration = mediaDuration ?? finiteTime(initialDuration)
  const currentTime = duration === null ? position : Math.min(position, duration)
  const canSeek = seekable && duration !== null && duration > 0 && !suspended
  const accessibleName = label ?? name

  // Reset the UI with the prop change, even if a pending play has no pause event.
  if (suspended && (playing || waiting)) {
    setPlaying(false)
    setWaiting(false)
  }

  const stop = () => {
    requested.current = false
    attempt.current++
    audio.current?.pause()
    if (activePlayer?.element === audio.current) activePlayer = undefined
    setPlaying(false)
    setWaiting(false)
  }

  useEffect(() => {
    const element = audio.current!
    // StrictMode can clean up and re-run this effect without replacing the node.
    element.setAttribute('src', src)
    return () => {
      requested.current = false
      if (activePlayer?.element === element) activePlayer = undefined
      element.pause()
      element.removeAttribute('src')
      element.load()
    }
  }, [src])

  useEffect(() => {
    if (!suspended) return
    requested.current = false
    attempt.current++
    const element = audio.current
    element?.pause()
    if (activePlayer?.element === element) activePlayer = undefined
  }, [suspended])

  useEffect(() => {
    if (!playing || waiting) return
    let frame: number
    const updatePosition = () => {
      const element = audio.current
      if (!element || element.paused || element.ended) return
      // timeupdate fires too infrequently for a smooth playback cursor.
      setPosition(finiteTime(element.currentTime) ?? 0)
      frame = requestAnimationFrame(updatePosition)
    }
    frame = requestAnimationFrame(updatePosition)
    return () => cancelAnimationFrame(frame)
  }, [playing, waiting])

  const sync = () => {
    const element = audio.current!
    setMediaDuration(finiteTime(element.duration))
    setPosition(finiteTime(element.currentTime) ?? 0)
    setSeekable(element.seekable.length > 0)
  }

  const fail = () => {
    stop()
    setError('暂时无法播放，请点击播放重试。')
  }

  const play = async () => {
    const element = audio.current
    if (!element || suspended) return
    if (requested.current || !element.paused) {
      stop()
      return
    }
    activePlayer?.stop()
    activePlayer = { element, stop }
    requested.current = true
    const request = ++attempt.current
    setError('')
    setWaiting(true)
    try {
      if (element.error) element.load()
      if (element.ended) element.currentTime = 0
      await element.play()
    } catch {
      if (attempt.current === request && requested.current) fail()
    }
  }

  const acceptPlay = () => {
    if (!requested.current || activePlayer?.element !== audio.current || suspended) {
      audio.current?.pause()
      return false
    }
    setPlaying(true)
    setError('')
    return true
  }

  return (
    <div className={styles.player}>
      <div className={styles.controls}>
        <button
          type="button"
          className={styles.play}
          aria-label={`${playing || waiting ? '暂停' : '播放'}${accessibleName}`}
          aria-busy={waiting}
          disabled={suspended}
          title={name}
          onClick={() => void play()}
        >
          {waiting ? (
            <LoaderCircle size={14} className={styles.spinner} />
          ) : playing ? (
            <Pause size={14} />
          ) : (
            <Play size={14} />
          )}
        </button>
        <input
          className={styles.seek}
          type="range"
          min={0}
          max={duration || 1}
          step="any"
          value={currentTime}
          disabled={!canSeek}
          aria-label={`${accessibleName}播放进度`}
          aria-valuetext={`${timeLabel(currentTime)} / ${timeLabel(duration)}`}
          style={
            { '--progress': `${duration ? (currentTime / duration) * 100 : 0}%` } as CSSProperties
          }
          onChange={(event) => {
            const element = audio.current
            if (!element || !canSeek) return
            const requestedTime = Number(event.target.value)
            let nearest = 0
            let distance = Infinity
            for (let index = 0; index < element.seekable.length; index++) {
              const candidate = Math.max(
                element.seekable.start(index),
                Math.min(element.seekable.end(index), requestedTime),
              )
              if (Math.abs(candidate - requestedTime) < distance) {
                nearest = candidate
                distance = Math.abs(candidate - requestedTime)
              }
            }
            if (!Number.isFinite(distance)) return
            try {
              element.currentTime = nearest
              setPosition(nearest)
            } catch {
              setSeekable(false)
            }
          }}
        />
        <span className={styles.time}>
          {timeLabel(currentTime)} / {timeLabel(duration)}
        </span>
      </div>
      <audio
        ref={audio}
        src={src}
        preload="none"
        aria-label={name}
        onLoadedMetadata={sync}
        onDurationChange={sync}
        onProgress={sync}
        onTimeUpdate={sync}
        onCanPlay={sync}
        onPlay={acceptPlay}
        onPlaying={() => {
          if (acceptPlay()) setWaiting(false)
        }}
        onWaiting={() => {
          if (requested.current) setWaiting(true)
        }}
        onPause={() => {
          // Ignore a delayed pause event if a newer play has already started.
          if (!audio.current?.paused) return
          requested.current = false
          attempt.current++
          if (activePlayer?.element === audio.current) activePlayer = undefined
          setPlaying(false)
          setWaiting(false)
        }}
        onEnded={() => {
          stop()
          sync()
        }}
        onError={fail}
      />
      {error && (
        <p className={styles.error} role="status">
          {error}
        </p>
      )}
    </div>
  )
}
