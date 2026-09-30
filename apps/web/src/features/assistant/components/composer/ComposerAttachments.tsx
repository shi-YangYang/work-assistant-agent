import styles from './ComposerAttachments.module.css'
import type { PreviewImage } from '@web/features/assistant/components/attachments/ImageGallery'
import { ComposerAudioPreview } from './ComposerAudioPreview'
import type { Composer } from '@web/features/assistant/lib/audio-capture'
import { fileKind, fileSize, isHeif } from '@web/features/assistant/utils/files'
import { FileText, X } from 'lucide-react'
import { useRef, type Dispatch, type SetStateAction } from 'react'

export function ComposerAttachments({
  composer,
  locked,
  setGallery,
  previewImages,
  setPdf,
  change,
}: {
  composer: Composer
  locked: boolean
  setGallery: Dispatch<SetStateAction<number | null>>
  previewImages: PreviewImage[]
  setPdf: Dispatch<SetStateAction<File | null>>
  change: (next: Composer) => void
}) {
  const playing = useRef<HTMLAudioElement | null>(null)
  const audioFiles = composer.files.filter((item) => fileKind(item.file) === 'audio')
  return (
    <div
      className={styles['pending-attachments']}
      role="region"
      aria-label={`待发送附件，共 ${composer.files.length} 个，可横向滚动`}
      tabIndex={0}
    >
      {composer.files.map((item) => {
        const kind = fileKind(item.file)
        const status = composer.uploading === item.id ? '上传中…' : item.failed ? '上传失败' : ''
        const title = `${item.file.name} · ${fileSize(item.file.size)}`
        const label = item.recorded ? `语音 ${audioFiles.indexOf(item) + 1}` : item.file.name
        return (
          <article
            key={item.id}
            className={styles['pending-file']}
            data-kind={kind}
            data-failed={!!item.failed}
            aria-label={label}
            aria-busy={composer.uploading === item.id}
          >
            {kind === 'image' ? (
              <button
                type="button"
                className={styles.image}
                title={title}
                aria-label={`预览${item.file.name}`}
                disabled={locked}
                onClick={() => setGallery(previewImages.findIndex((image) => image.id === item.id))}
              >
                {isHeif(item.file) && !item.attachment ? (
                  <span>HEIC</span>
                ) : (
                  <img src={item.attachment?.previewUrl ?? item.url} alt="" />
                )}
              </button>
            ) : kind === 'audio' ? (
              <ComposerAudioPreview
                file={item.file}
                src={item.attachment?.previewUrl ?? item.url}
                recorded={item.recorded}
                label={label}
                status={status}
                onPlay={(audio) => {
                  if (playing.current !== audio) playing.current?.pause()
                  playing.current = audio
                }}
              />
            ) : (
              <button
                type="button"
                className={styles.document}
                title={title}
                aria-label={`预览${item.file.name}`}
                disabled={locked || !item.file.name.toLowerCase().endsWith('.pdf')}
                onClick={() => setPdf(item.file)}
              >
                <FileText size={24} />
                <span>
                  <strong>{item.file.name}</strong>
                  <small>{item.file.name.split('.').pop()?.toUpperCase()}</small>
                </span>
              </button>
            )}
            {status && kind !== 'audio' && (
              <span className={styles.status} role="status">
                {status}
              </span>
            )}
            <button
              type="button"
              className={styles.remove}
              disabled={locked}
              title={`移除${label}`}
              aria-label={`移除${label}`}
              onClick={() => {
                URL.revokeObjectURL(item.url)
                change({
                  ...composer,
                  key: '',
                  files: composer.files.filter((f) => f.id !== item.id),
                })
              }}
            >
              <X size={14} />
            </button>
          </article>
        )
      })}
    </div>
  )
}
