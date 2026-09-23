import utilitiesStyles from '../../../styles/utilities.module.css'
import layoutStyles from '../../../styles/layout.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import documentsStyles from '../styles/documents.module.css'
import type { Attachment, DocumentCitation, ExtractionPage } from '@paa/api-contracts'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Modal } from '@web/components/Modal'
import { documentExtractionPath, retryDocument } from '@web/features/assistant/api/requests'
import { PdfPreview } from '@web/features/assistant/components/PdfPreview'
import { currentCitation, fileSize } from '@web/features/assistant/utils/files'
import { useResource } from '@web/hooks/useResource'
import { Download, FileText } from 'lucide-react'
import { useState } from 'react'

const statuses: Record<string, string> = {
  unsent: '上传完成，尚未发送',
  pending: '等待解析',
  processing: '正在解析',
  ready: '文字可读',
  partial: '部分可读',
  failed: '解析失败',
}

export function DocumentCard({
  attachment,
  own,
  refresh,
}: {
  attachment: Attachment
  own: boolean
  refresh: () => void
}) {
  const [open, setOpen] = useState(false)
  const [pdf, setPdf] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  const extraction = attachment.extraction
  return (
    <div className={documentsStyles['document-card']}>
      <div className={documentsStyles['document-heading']}>
        <FileText size={21} />
        <strong>{attachment.name}</strong>
      </div>
      <p className={`${utilitiesStyles['muted']} ${utilitiesStyles['small-text']}`}>
        {attachment.name.split('.').pop()?.toUpperCase()} · {fileSize(attachment.size)} ·{' '}
        {statuses[extraction?.status ?? 'pending']}
      </p>
      {extraction?.error && (
        <p className={documentsStyles['document-warning']}>{extraction.error}</p>
      )}
      {extraction?.warnings?.map((warning) => (
        <p className={documentsStyles['document-warning']} key={warning}>
          {warning}
        </p>
      ))}
      <div className={`${layoutStyles['card-actions']} ${documentsStyles['slot-card-actions']}`}>
        {attachment.mime === 'application/pdf' && (
          <button className={`${controlsStyles['text-button']}`} onClick={() => setPdf(true)}>
            查看原页
          </button>
        )}
        {['ready', 'partial'].includes(extraction?.status ?? '') && (
          <button className={`${controlsStyles['text-button']}`} onClick={() => setOpen(true)}>
            查看提取内容
          </button>
        )}
        <a href={attachment.url} download={attachment.name}>
          <Download size={14} />
          下载原文件
        </a>
        {own && extraction?.status === 'failed' && (
          <BusyButton
            busy={busy}
            onClick={async () => {
              setBusy(true)
              try {
                await retryDocument(attachment, {})
                refresh()
                setError('')
              } catch (e) {
                setError(e as Error)
              } finally {
                setBusy(false)
              }
            }}
          >
            重新解析
          </BusyButton>
        )}
      </div>
      {extraction?.status === 'failed' && (
        <p className={`${utilitiesStyles['muted']} ${utilitiesStyles['small-text']}`}>
          可重新解析，或修正文件后重新发送。
        </p>
      )}
      <ErrorNotice>{error}</ErrorNotice>
      {pdf && (
        <PdfPreview name={attachment.name} url={attachment.url} onClose={() => setPdf(false)} />
      )}
      {open && (
        <DocumentPreview
          attachmentId={attachment.id}
          revision={extraction?.revision}
          name={attachment.name}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  )
}

export function DocumentPreview({
  attachmentId,
  revision,
  name,
  ordinal = 0,
  onClose,
}: {
  attachmentId: string
  revision?: number
  name: string
  ordinal?: number
  onClose: () => void
}) {
  const [starts, setStarts] = useState([ordinal])
  const start = starts[starts.length - 1]
  const { data, error, refresh } = useResource<ExtractionPage>(
    documentExtractionPath(attachmentId, start, revision),
    2000,
  )
  return (
    <Modal title={name} onClose={onClose}>
      <div className={documentsStyles['document-preview']}>
        <ErrorNotice retry={refresh}>{error}</ErrorNotice>
        {data && !error && (
          <>
            <p className={`${utilitiesStyles['muted']} ${utilitiesStyles['small-text']}`}>
              {data.attachment.extraction?.scope ?? '提取文字'} ·{' '}
              {statuses[data.attachment.extraction?.status ?? 'pending']}
            </p>
            {data.attachment.extraction?.warnings?.map((warning) => (
              <p className={documentsStyles['document-warning']} key={warning}>
                {warning}
              </p>
            ))}
            {data.items.map((chunk) => (
              <section key={chunk.ordinal}>
                <h4>{chunk.location}</h4>
                <pre>{chunk.text}</pre>
              </section>
            ))}
            <div className={layoutStyles['row-between']}>
              <button disabled={starts.length === 1} onClick={() => setStarts(starts.slice(0, -1))}>
                上一组
              </button>
              <span className={`${utilitiesStyles['muted']} ${utilitiesStyles['small-text']}`}>
                分段 {start + 1}–{start + data.items.length}
              </span>
              <button
                disabled={data.nextCursor === null}
                onClick={() => setStarts([...starts, data.nextCursor!])}
              >
                下一组
              </button>
            </div>
          </>
        )}
      </div>
    </Modal>
  )
}

export function DocumentCitations({ citations }: { citations: DocumentCitation[] }) {
  const [selected, setSelected] = useState<DocumentCitation | null>(null)
  return (
    <div className={documentsStyles['document-citations']}>
      {citations.map((citation, index) => (
        <button
          className={`${controlsStyles['text-button']}`}
          key={`${citation.attachmentId}:${citation.ordinal}`}
          onClick={() => setSelected(citation)}
        >
          〔{index + 1}〕{citation.name} · {citation.location}
        </button>
      ))}
      {selected && currentCitation(citations, selected) && (
        <DocumentPreview
          key={`${selected.attachmentId}:${selected.ordinal}`}
          attachmentId={selected.attachmentId}
          revision={selected.revision}
          ordinal={selected.ordinal}
          name={selected.name}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  )
}
