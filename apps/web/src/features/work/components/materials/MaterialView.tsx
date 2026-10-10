import type { Attachment } from '@paa/api-contracts'
import { DocumentCard } from '@web/components/media/Documents'
import { ImageGallery } from '@web/components/media/ImageGallery'
import { fileSize } from '@web/utils/attachments'
import { useState } from 'react'
import styles from './WorkMaterials.module.css'

export function MaterialView({
  attachment,
  own = false,
  refresh = () => {},
}: {
  attachment: Attachment
  own?: boolean
  refresh?: () => void
}) {
  const [preview, setPreview] = useState(false)
  if (attachment.kind === 'document')
    return <DocumentCard attachment={attachment} own={own} refresh={refresh} compact />
  return (
    <div className={styles.media}>
      {attachment.kind === 'image' ? (
        <button
          type="button"
          className={styles.image}
          aria-label={`预览 ${attachment.name}`}
          onClick={() => setPreview(true)}
        >
          <img src={attachment.previewUrl ?? attachment.url} alt={attachment.name} loading="lazy" />
        </button>
      ) : (
        <audio controls preload="metadata" src={attachment.url} aria-label={attachment.name} />
      )}
      <div className={styles.caption}>
        <a href={attachment.url} download={attachment.name}>
          {attachment.name}
        </a>
        <small>{fileSize(attachment.size)}</small>
      </div>
      {preview && (
        <ImageGallery
          images={[
            {
              id: attachment.id,
              name: attachment.name,
              src: attachment.previewUrl ?? attachment.url,
              original: attachment.url,
            },
          ]}
          initial={0}
          onClose={() => setPreview(false)}
        />
      )}
    </div>
  )
}
