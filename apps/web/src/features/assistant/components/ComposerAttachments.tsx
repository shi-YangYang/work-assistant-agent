import controlsStyles from '../../../styles/controls.module.css'
import styles from './ComposerAttachments.module.css'
import attachmentsStyles from '../styles/attachments.module.css'
import type { PreviewImage } from '@web/features/assistant/components/ImageGallery'
import { RecordingPreview } from '@web/features/assistant/components/RecordingPreview'
import type { Composer } from '@web/features/assistant/lib/audio-capture'
import { fileKind, fileSize, isHeif } from '@web/features/assistant/utils/files'
import { FileText, X } from 'lucide-react'
import type * as React from 'react'

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
  setGallery: React.Dispatch<React.SetStateAction<number | null>>
  previewImages: PreviewImage[]
  setPdf: React.Dispatch<React.SetStateAction<File | null>>
  change: (next: Composer) => void
}) {
  return (
    <div className={styles['pending-attachments']}>
      {(['audio', 'image', 'document'] as const).map((kind) => {
        const files = composer.files.filter((item) => fileKind(item.file) === kind)
        return (
          files.length > 0 && (
            <div className={styles['pending-group']} data-kind={kind} key={kind}>
              {files.map((item) => (
                <div key={item.id} className={styles['pending-file']} data-kind={kind}>
                  {fileKind(item.file) === 'image' ? (
                    <button
                      className={`${attachmentsStyles['attachment-preview-button']} ${styles['slot-attachment-preview-button']}`}
                      aria-label={`预览${item.file.name}`}
                      disabled={locked}
                      onClick={() =>
                        setGallery(previewImages.findIndex((image) => image.id === item.id))
                      }
                    >
                      {isHeif(item.file) && !item.attachment ? (
                        <span>HEIC</span>
                      ) : (
                        <img src={item.attachment?.previewUrl ?? item.url} alt={item.file.name} />
                      )}
                    </button>
                  ) : kind === 'audio' ? (
                    <div className={styles['pending-audio-player']}>
                      {item.recorded ? (
                        <RecordingPreview file={item.file} />
                      ) : (
                        <audio
                          controls
                          src={item.attachment?.previewUrl ?? item.url}
                          preload="metadata"
                          aria-label={`试听${item.file.name}`}
                        />
                      )}
                    </div>
                  ) : item.file.name.toLowerCase().endsWith('.pdf') ? (
                    <button
                      className={`${attachmentsStyles['attachment-preview-button']} ${styles['slot-attachment-preview-button']}`}
                      aria-label={`预览${item.file.name}`}
                      onClick={() => setPdf(item.file)}
                    >
                      <FileText size={24} />
                    </button>
                  ) : (
                    <FileText size={24} />
                  )}
                  <div className={styles['pending-file-info']}>
                    <strong>{item.file.name}</strong>
                    <span>
                      {item.file.name.split('.').pop()?.toUpperCase()} · {fileSize(item.file.size)}{' '}
                      ·{' '}
                      {composer.uploading === item.id
                        ? '正在上传…'
                        : item.attachment
                          ? '上传完成'
                          : item.failed
                            ? '上传未完成，可重试'
                            : '待上传'}
                    </span>
                  </div>
                  <button
                    className={controlsStyles['icon-button']}
                    disabled={locked}
                    aria-label={`移除${item.file.name}`}
                    onClick={() => {
                      URL.revokeObjectURL(item.url)
                      change({
                        ...composer,
                        key: '',
                        files: composer.files.filter((f) => f.id !== item.id),
                      })
                    }}
                  >
                    <X size={15} />
                  </button>
                </div>
              ))}
            </div>
          )
        )
      })}
    </div>
  )
}
