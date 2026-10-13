import type { DeliverableFile, DeliverableSummary } from '@paa/api-contracts'
import { ApiError } from '@web/api/client'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { ImageGallery } from '@web/components/media/ImageGallery'
import { Download, FileText, LoaderCircle, Presentation, Sheet } from 'lucide-react'
import { useState } from 'react'
import { useGeneratedFile, useGeneratedImage } from '../../hooks/deliverables/useGeneratedFile'
import { fileSize } from '../../utils/files'
import styles from './GeneratedFiles.module.css'

export function GeneratedFiles({
  deliverableId,
  revision,
  files = [],
  includeImages = true,
}: {
  deliverableId: string
  revision: number
  files?: DeliverableFile[]
  includeImages?: boolean
}) {
  const visible = includeImages ? files : files.filter((file) => file.mimeType !== 'image/png')
  if (!visible.length) return null
  return (
    <ul className={styles.files} aria-label={`生成文件 · 版本 ${revision}`}>
      {visible.map((file) => (
        <GeneratedFile
          key={`${deliverableId}:${revision}:${file.id}`}
          deliverableId={deliverableId}
          revision={revision}
          file={file}
        />
      ))}
    </ul>
  )
}

export function GeneratedImages({ items }: { items: DeliverableSummary[] }) {
  const images = items.flatMap((item) =>
    (item.files ?? [])
      .filter((file) => file.mimeType === 'image/png')
      .map((file) => ({ deliverableId: item.id, revision: item.revision, file })),
  )
  if (!images.length) return null
  return (
    <ul className={`${styles.files} ${styles.images}`} aria-label="生成图片">
      {images.map((image) => (
        <GeneratedFile
          key={`${image.deliverableId}:${image.revision}:${image.file.id}`}
          {...image}
        />
      ))}
    </ul>
  )
}

function GeneratedFile({
  deliverableId,
  revision,
  file,
}: {
  deliverableId: string
  revision: number
  file: DeliverableFile
}) {
  const { download, busy, error } = useGeneratedFile(deliverableId, revision, file)
  const unavailable = error instanceof ApiError && [401, 403, 404].includes(error.status)
  if (file.mimeType === 'image/png') {
    return (
      <li className={styles['image-file']}>
        {unavailable ? (
          <ErrorNotice retry={() => void download()}>{error}</ErrorNotice>
        ) : (
          <GeneratedImage
            deliverableId={deliverableId}
            revision={revision}
            file={file}
            download={{ run: () => void download(), busy, error }}
          />
        )}
      </li>
    )
  }
  const format = file.name.split('.').pop()?.toUpperCase() ?? '文件'
  const Icon =
    format === 'PPTX' ? Presentation : ['XLSX', 'CSV'].includes(format) ? Sheet : FileText
  return (
    <li className={styles.file}>
      <div className={styles.row}>
        <span className={styles.icon} aria-hidden="true">
          <Icon size={20} />
        </span>
        <div className={styles.description}>
          <strong title={file.name}>{file.name}</strong>
          <span>
            {format} · {fileSize(file.size)}
            {file.width && file.height ? ` · ${file.width} × ${file.height}` : ''} · 版本 {revision}
          </span>
        </div>
        <button
          className={styles.download}
          type="button"
          onClick={() => void download()}
          disabled={busy}
          aria-label={`${busy ? '正在下载' : '下载'}${file.name}`}
        >
          {busy ? (
            <LoaderCircle size={17} className={styles.spinning} aria-hidden="true" />
          ) : (
            <Download size={17} aria-hidden="true" />
          )}
          <span>{busy ? '下载中' : '下载'}</span>
        </button>
      </div>
      <ErrorNotice retry={() => void download()}>{error}</ErrorNotice>
    </li>
  )
}

function GeneratedImage({
  deliverableId,
  revision,
  file,
  download,
}: {
  deliverableId: string
  revision: number
  file: DeliverableFile
  download: { run: () => void; busy: boolean; error: Error | string }
}) {
  const { url, error, retry } = useGeneratedImage(deliverableId, revision, file)
  const [failedUrl, setFailedUrl] = useState('')
  const [open, setOpen] = useState(false)
  return (
    <div className={styles.preview}>
      {url && url !== failedUrl ? (
        <button
          className={styles.thumbnail}
          type="button"
          aria-label={`预览${file.name}`}
          onClick={() => setOpen(true)}
        >
          <img src={url} alt={file.name} onError={() => setFailedUrl(url)} />
        </button>
      ) : url ? (
        <>
          <span className={styles.loading}>图片无法预览，可下载文件查看。</span>
          <button
            className={styles.download}
            disabled={download.busy}
            onClick={download.run}
            aria-label={`下载${file.name}`}
          >
            <Download size={17} aria-hidden="true" />
            下载
          </button>
        </>
      ) : error ? (
        <ErrorNotice retry={retry}>{error}</ErrorNotice>
      ) : (
        <span className={styles.loading} role="status">
          正在读取图片…
        </span>
      )}
      {!open && <ErrorNotice retry={download.run}>{download.error}</ErrorNotice>}
      {open && url && (
        <ImageGallery
          images={[{ id: file.id, name: file.name, src: url, original: file.url }]}
          initial={0}
          onClose={() => setOpen(false)}
          download={download}
        />
      )}
    </div>
  )
}
