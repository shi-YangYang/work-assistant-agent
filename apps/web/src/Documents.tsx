import { useState } from 'react'
import { FileText, Download } from 'lucide-react'
import type { Attachment, DocumentCitation, ExtractionPage } from '@paa/api-contracts'
import { useResource, write } from './api'
import { currentCitation, fileSize } from './files'
import { BusyButton, ErrorNotice, Modal } from './ui'

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
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const extraction = attachment.extraction
  return (
    <div className="document-card">
      <div className="document-heading">
        <FileText size={21} />
        <strong>{attachment.name}</strong>
      </div>
      <p className="muted small-text">
        {attachment.name.split('.').pop()?.toUpperCase()} · {fileSize(attachment.size)} ·{' '}
        {statuses[extraction?.status ?? 'pending']}
      </p>
      {extraction?.error && <p className="document-warning">{extraction.error}</p>}
      {extraction?.warnings?.map((warning) => (
        <p className="document-warning" key={warning}>
          {warning}
        </p>
      ))}
      <div className="card-actions">
        {['ready', 'partial'].includes(extraction?.status ?? '') && (
          <button className="text-button" onClick={() => setOpen(true)}>
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
                await write(`/uploads/${attachment.id}/retry`, {})
                refresh()
                setError('')
              } catch (e) {
                setError((e as Error).message)
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
        <p className="muted small-text">可重新解析，或修正文件后重新发送。</p>
      )}
      <ErrorNotice>{error}</ErrorNotice>
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
    `/uploads/${attachmentId}/extraction?start=${start}${revision !== undefined ? `&revision=${revision}` : ''}`,
    2000,
  )
  return (
    <Modal title={name} onClose={onClose}>
      <div className="document-preview">
        <ErrorNotice retry={refresh}>{error}</ErrorNotice>
        {data && !error && (
          <>
            <p className="muted small-text">
              {data.attachment.extraction?.scope ?? '提取文字'} ·{' '}
              {statuses[data.attachment.extraction?.status ?? 'pending']}
            </p>
            {data.attachment.extraction?.warnings?.map((warning) => (
              <p className="document-warning" key={warning}>
                {warning}
              </p>
            ))}
            {data.items.map((chunk) => (
              <section key={chunk.ordinal}>
                <h4>{chunk.location}</h4>
                <pre>{chunk.text}</pre>
              </section>
            ))}
            <div className="row-between">
              <button disabled={starts.length === 1} onClick={() => setStarts(starts.slice(0, -1))}>
                上一组
              </button>
              <span className="muted small-text">
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
    <div className="document-citations">
      {citations.map((citation, index) => (
        <button
          className="text-button"
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
