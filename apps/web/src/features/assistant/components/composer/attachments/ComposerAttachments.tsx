import { Modal } from '@web/components/overlays/Modal'
import { attachmentUploads } from '../../../lib/attachment-uploads'
import styles from './ComposerAttachments.module.css'
import type { PreviewImage } from '@web/components/media/ImageGallery'
import { ComposerAudioPreview } from './ComposerAudioPreview'
import type { Composer } from '@web/features/assistant/lib/audio-capture'
import { fileKind, fileSize, isHeif, isLegacyOfficeFile } from '@web/features/assistant/utils/files'
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
          const failed = !!item.failed && !uploading
          const status = uploading
            ? '上传中…'
            : failed
              ? item.uploadError || '上传失败'
              : !item.attachment
                ? '等待上传'
                : ''
          const title = `${item.file.name} · ${fileSize(item.file.size)}`
          const label = item.recorded ? `语音 ${audioFiles.indexOf(item) + 1}` : item.file.name
          const format = item.file.name.split('.').slice(1).pop()?.toUpperCase() || '文件'
          return (
            <article
              key={item.id}
              className={styles['pending-file']}
              data-kind={kind}
              data-failed={failed}
              aria-label={label}
              aria-busy={uploading}
            >
              {kind === 'audio' && !failed ? (
                <ComposerAudioPreview
                  file={item.file}
                  src={item.attachment?.previewUrl ?? item.url}
                  recorded={item.recorded}
                  label={label}
                  status={status}
                  uploading={uploading}
                  onPlay={(audio) => {
                    if (playing.current !== audio) playing.current?.pause()
                    playing.current = audio
                  }}
                />
              ) : (
                <button
                  type="button"
                  className={kind === 'image' ? styles.image : styles.document}
                  title={failed ? status : title}
                  aria-label={failed ? `重试上传${label}` : `预览${item.file.name}`}
                  disabled={locked}
                  onClick={() =>
                    failed
                      ? attachmentUploads.retry(item.id)
                      : kind === 'image'
                        ? setGallery(previewImages.findIndex((image) => image.id === item.id))
                        : item.file.name.toLowerCase().endsWith('.pdf')
                          ? setPdf(item.file)
                          : setName(item.file.name)
                  }
                >
                  <span
                    className={styles.thumbnail}
                    data-format={!failed && !uploading ? format : undefined}
                  >
                    {kind === 'image' ? (
                      isHeif(item.file) && !item.attachment ? (
                        <span>HEIC</span>
                      ) : (
                        <img src={item.attachment?.previewUrl ?? item.url} alt="" />
                      )
                    ) : failed ? (
                      <RotateCw size={20} />
                    ) : uploading ? (
                      <LoaderCircle size={20} className={styles.spinner} aria-label="上传中" />
                    ) : (
                      <FileText size={20} />
                    )}
                  </span>
                  {kind === 'image' ? (
                    (uploading || failed) && (
                      <span className={styles['image-status']} title={status} role="status">
                        {uploading ? (
                          <LoaderCircle size={20} className={styles.spinner} aria-label="上传中" />
                        ) : (
                          <>
                            <RotateCw size={18} />
                            <small>上传失败</small>
                          </>
                        )}
                      </span>
                    )
                  ) : (
                    <span>
                      <strong>{label}</strong>
                      <small title={status || title} role={status ? 'status' : undefined}>
                        {status || `${format} · ${fileSize(item.file.size)}`}
                      </small>
                    </span>
                  )}
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
      {files.some((item) => isLegacyOfficeFile(item.file.name)) && (
        <p className={styles['compatibility-tip']} role="note" aria-label="旧版 Office 兼容提示">
          旧版 Office 文件可能解析失败或内容不完整，建议先用 Microsoft Office 或 WPS 另存为
          DOCX、XLSX、PPTX 后上传。
        </p>
      )}
    </>
  )
}
