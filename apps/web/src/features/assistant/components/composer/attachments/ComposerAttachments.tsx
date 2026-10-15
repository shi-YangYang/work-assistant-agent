import { Modal } from '@web/components/overlays/Modal'
import { attachmentUploads } from '../../../lib/attachment-uploads'
import styles from './ComposerAttachments.module.css'
import type { PreviewImage } from '@web/components/media/ImageGallery'
import { ComposerAudioPreview } from './ComposerAudioPreview'
import type { Composer } from '@web/features/assistant/lib/audio-capture'
import { fileKind, fileSize, isHeif } from '@web/features/assistant/utils/files'
import { FileText, LoaderCircle, RotateCw, X } from 'lucide-react'
import { useRef, useState, type Dispatch, type SetStateAction } from 'react'

export function ComposerAttachments({
  composer,
  directSendingFile,
  locked,
  setGallery,
  previewImages,
  setPdf,
  change,
}: {
  composer: Composer
  directSendingFile?: File | null
  locked: boolean
  setGallery: Dispatch<SetStateAction<number | null>>
  previewImages: PreviewImage[]
  setPdf: Dispatch<SetStateAction<File | null>>
  change: (next: Composer) => void
}) {
  const [name, setName] = useState('')
  const playing = useRef<HTMLAudioElement | null>(null)
  const files = composer.files.filter((item) => item.file !== directSendingFile)
  const audioFiles = files.filter((item) => fileKind(item.file) === 'audio')
  if (!files.length) return null
  return (
    <>
      {name && (
        <Modal title="附件名称" onClose={() => setName('')}>
          <p className={styles['full-name']}>{name}</p>
        </Modal>
      )}
      <div
        className={styles['pending-attachments']}
        role="region"
        aria-label={`待发送附件，共 ${files.length} 个，可横向滚动`}
        tabIndex={0}
      >
        {files.map((item) => {
          const kind = fileKind(item.file)
          const uploading = item.uploadState === 'uploading' || composer.uploading === item.id
          const status = uploading
            ? '上传中…'
            : item.failed
              ? item.uploadError || '上传失败'
              : !item.attachment
                ? '等待上传'
                : ''
          const title = `${item.file.name} · ${fileSize(item.file.size)}`
          const label = item.recorded ? `语音 ${audioFiles.indexOf(item) + 1}` : item.file.name
          return (
            <article
              key={item.id}
              className={styles['pending-file']}
              data-kind={kind}
              data-failed={!!item.failed}
              aria-label={label}
              aria-busy={uploading}
            >
              {kind === 'image' ? (
                <button
                  type="button"
                  className={styles.image}
                  title={title}
                  aria-label={`预览${item.file.name}`}
                  disabled={locked}
                  onClick={() =>
                    setGallery(previewImages.findIndex((image) => image.id === item.id))
                  }
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
                  disabled={locked}
                  onClick={() =>
                    item.file.name.toLowerCase().endsWith('.pdf')
                      ? setPdf(item.file)
                      : setName(item.file.name)
                  }
                >
                  {uploading ? (
                    <LoaderCircle size={18} className={styles.spinner} aria-label="上传中" />
                  ) : (
                    <FileText size={18} />
                  )}
                  <span>
                    <strong>{item.file.name}</strong>
                    <small title={status || title} role={status ? 'status' : undefined}>
                      {status || fileSize(item.file.size)}
                    </small>
                  </span>
                </button>
              )}
              {status && kind === 'image' && (
                <span className={styles.status} role="status">
                  {uploading && (
                    <LoaderCircle size={12} className={styles.spinner} aria-hidden="true" />
                  )}{' '}
                  {status}
                </span>
              )}
              {kind === 'audio' && uploading && (
                <LoaderCircle
                  size={16}
                  className={`${styles.spinner} ${styles['audio-spinner']}`}
                  aria-label="上传中"
                />
              )}
              {item.failed && (
                <button
                  type="button"
                  className={styles.retry}
                  disabled={locked}
                  aria-label={`重试上传${label}`}
                  title="重试上传"
                  onClick={() => attachmentUploads.retry(item.id)}
                >
                  <RotateCw size={14} />
                </button>
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
    </>
  )
}
