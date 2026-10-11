import { recordingPreview } from '@web/features/assistant/lib/audio-preview'
import { Pause, Play, X } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import styles from './ComposerAudioPreview.module.css'

export function ComposerAudioPreview({
  file,
  src,
  recorded,
  label,
  status,
  onPlay,
}: {
  file: File
  src: string
  recorded?: boolean
  label: string
  status: string
  onPlay: (audio: HTMLAudioElement) => void
}) {
  const [preview, setPreview] = useState<{ file: File; url?: string; failed?: boolean }>()
  const [duration, setDuration] = useState<number>()
  const [playing, setPlaying] = useState(false)
  const [error, setError] = useState('')
  const [open, setOpen] = useState(false)
  const audio = useRef<HTMLAudioElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const id = useId()
  const url = recorded ? (preview?.file === file ? preview.url : undefined) : src
  const failed = !!error || (recorded && preview?.file === file && preview.failed)

  useEffect(() => {
    if (!recorded) return
    let disposed = false
    let objectUrl = ''
    void recordingPreview(file).then(
      (blob) => {
        if (disposed) return
        objectUrl = URL.createObjectURL(blob)
        setPreview({ file, url: objectUrl })
      },
      () => {
        if (!disposed) setPreview({ file, failed: true })
      },
    )
    return () => {
      disposed = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [file, recorded])

  useEffect(() => {
    const element = audio.current
    return () => element?.pause()
  }, [])

  const place = () => {
    const rect = trigger.current?.closest('article')?.getBoundingClientRect()
    if (!rect || !panel.current) return
    const width = Math.min(360, window.innerWidth - 24)
    panel.current.style.left = `${Math.max(12, Math.min(rect.left, window.innerWidth - width - 12))}px`
    panel.current.style.bottom = `${Math.max(12, Math.min(window.innerHeight - rect.top + 10, window.innerHeight - 160))}px`
  }
  useEffect(() => {
    if (!open) return
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [open])

  const togglePlayback = () => {
    const element = audio.current
    if (!element || !url) return
    if (!element.paused) element.pause()
    else {
      setError('')
      onPlay(element)
      void element.play().catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === 'AbortError'))
          setError('无法试听，请展开播放器重试。')
      })
    }
  }
  const readDuration = () => {
    const value = audio.current?.duration
    if (value && Number.isFinite(value)) setDuration(value)
  }
  const time = duration
    ? `${Math.floor(duration / 60)}:${String(Math.floor(duration % 60)).padStart(2, '0')}`
    : url
      ? '读取时长…'
      : '准备试听…'

  return (
    <>
      <button
        type="button"
        className={styles.play}
        aria-label={`${playing ? '暂停' : '播放'}${label}`}
        disabled={!url}
        onClick={togglePlayback}
      >
        {playing ? <Pause size={16} /> : <Play size={16} />}
      </button>
      <button
        type="button"
        ref={trigger}
        className={styles.info}
        title={`${file.name} · 展开试听`}
        aria-label={`展开${label}试听`}
        aria-haspopup="dialog"
        aria-expanded={open}
        popoverTarget={id}
      >
        <strong>{label}</strong>
        <span role="status" data-failed={failed || status === '上传失败'}>
          {status || (failed ? '无法试听' : time)}
        </span>
      </button>
      <div
        ref={panel}
        id={id}
        popover="auto"
        role="dialog"
        aria-label={`${label}试听详情`}
        className={styles.panel}
        onBeforeToggle={(event) => {
          if (event.newState === 'open') place()
        }}
        onToggle={(event) => setOpen(event.newState === 'open')}
      >
        <header>
          <strong title={file.name}>{label}</strong>
          <button
            type="button"
            aria-label="关闭试听详情"
            popoverTarget={id}
            popoverTargetAction="hide"
          >
            <X size={16} />
          </button>
        </header>
        <audio
          ref={audio}
          controls
          src={url}
          preload="metadata"
          aria-label={`试听${label}`}
          onLoadedMetadata={readDuration}
          onDurationChange={readDuration}
          onPlay={(event) => {
            onPlay(event.currentTarget)
            setPlaying(true)
            setError('')
          }}
          onPause={() => setPlaying(false)}
          onEnded={() => setPlaying(false)}
          onError={() => setError('暂时无法试听，可发送原文件后播放。')}
        />
        {(failed || !url) && (
          <p role="status">
            {error || (failed ? '暂时无法试听，可发送原文件后播放。' : '正在准备录音试听…')}
          </p>
        )}
      </div>
    </>
  )
}
