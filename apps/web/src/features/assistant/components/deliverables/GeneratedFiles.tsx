import type { DeliverableFile } from '@paa/api-contracts'
import { ApiError } from '@web/api/client'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { Download, FileText, Image, LoaderCircle, Presentation, Sheet } from 'lucide-react'
import { useState } from 'react'
import { useGeneratedFile, useGeneratedImage } from '../../hooks/useGeneratedFile'
import { fileSize } from '../../utils/files'
import styles from './GeneratedFiles.module.css'

export function GeneratedFiles({
  deliverableId,
  revision,
  files = [],
}: {
  deliverableId: string
  revision: number
  files?: DeliverableFile[]
}) {
  if (!files.length) return null
  return (
    <ul className={styles.files} aria-label={`生成文件 · 版本 ${revision}`}>
      {files.map((file) => (
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
  const format = file.name.split('.').pop()?.toUpperCase() ?? '文件'
  const Icon =
    file.mimeType === 'image/png'
      ? Image
      : format === 'PPTX'
        ? Presentation
        : ['XLSX', 'CSV'].includes(format)
          ? Sheet
          : FileText
  return (
    <li className={styles.file}>
      {file.mimeType === 'image/png' && !unavailable && (
        <GeneratedImage deliverableId={deliverableId} revision={revision} file={file} />
      )}
      <div className={styles.row}>
        <span className={styles.icon} aria-hidden="true">
          <Icon size={20} />
        </span>
        <div className={styles.description}>
          <strong title={file.name}>{file.name}</strong>
          <span>
            {format} · {fileSize(file.size)} · 版本 {revision}
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
}: {
  deliverableId: string
  revision: number
  file: DeliverableFile
}) {
  const { url, error, retry } = useGeneratedImage(deliverableId, revision, file)
  const [failedUrl, setFailedUrl] = useState('')
  return (
    <div className={styles.preview}>
      {url && url !== failedUrl ? (
        <img src={url} alt={file.name} onError={() => setFailedUrl(url)} />
      ) : url ? (
        <span className={styles.loading}>图片无法预览，可下载文件查看。</span>
      ) : error ? (
        <ErrorNotice retry={retry}>{error}</ErrorNotice>
      ) : (
        <span className={styles.loading} role="status">
          正在读取图片…
        </span>
      )}
    </div>
  )
}
