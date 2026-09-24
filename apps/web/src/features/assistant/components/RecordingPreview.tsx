import utilitiesStyles from '../../../styles/utilities.module.css'
import { recordingPreview } from '@web/features/assistant/lib/audio-preview'
import { useEffect, useState } from 'react'

export function RecordingPreview({ file }: { file: File }) {
  const [preview, setPreview] = useState<{ file: File; url?: string; failed?: boolean }>()
  useEffect(() => {
    let disposed = false
    let url = ''
    void recordingPreview(file).then(
      (blob) => {
        if (disposed) return
        url = URL.createObjectURL(blob)
        setPreview({ file, url })
      },
      () => {
        if (!disposed) setPreview({ file, failed: true })
      },
    )
    return () => {
      disposed = true
      if (url) URL.revokeObjectURL(url)
    }
  }, [file])
  if (preview?.file === file && preview.url)
    return <audio controls src={preview.url} preload="metadata" aria-label={`试听${file.name}`} />
  return (
    <p className={`${utilitiesStyles['muted']} ${utilitiesStyles['small-text']}`} role="status">
      {preview?.file === file && preview.failed
        ? '暂时无法试听，可发送原录音后播放。'
        : '正在准备录音试听…'}
    </p>
  )
}
