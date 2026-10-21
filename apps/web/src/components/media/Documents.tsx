import utilitiesStyles from '../../styles/utilities.module.css'
import layoutStyles from '../../styles/layout.module.css'
import controlsStyles from '../../styles/controls.module.css'
import documentsStyles from './documents.module.css'
import cardStyles from '@web/styles/patterns/ResourceCard.module.css'
import type { Attachment, DocumentCitation, ExtractionPage } from '@paa/api-contracts'
import { BusyButton } from '@web/components/actions/BusyButton'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { Modal } from '@web/components/overlays/Modal'
import { documentExtractionPath, retryDocument } from '@web/api/attachments'
import { PdfPreview } from './PdfPreview'
import { currentCitation, fileSize } from '@web/utils/attachments'
import { useResource } from '@web/hooks/useResource'
import { ChevronDown, Download, FileText } from 'lucide-react'
import { useState } from 'react'

const statuses: Record<string, string> = {
  unsent: '上传完成，尚未发送',
  pending: '等待解析',
  processing: '正在解析',
  ready: '',
  partial: '部分可读',
  failed: '解析失败',
  empty: '未找到文字',
}

function extractionStatus(extraction: Attachment['extraction']) {
  if (extraction?.hasVisuals && extraction.characters === 0 && extraction.status !== 'failed')
    return ''

  if (extraction?.status === 'processing') {
    switch (extraction.stage) {
      case 'queued':
        return '等待转换'
      case 'converting':
        return '正在转换'
      case 'parsing':
        return '正在读取'
    }
  }
  return statuses[extraction?.status ?? 'pending']
}

const failureHints: [RegExp, string][] = [
  [/已加密或结构损坏/, '文件有密码或已损坏，请检查后重新上传。'],
  [/加密|密码/, '文件有密码，请解密后上传。'],
  [/公式/, '公式结果无法确认，请用 Office 或 WPS 另存为 XLSX 后上传。'],
  [/没有可提取文字/, '没找到文字，请上传带文字的文件。'],
  [/编码/, '文字编码不支持，请保存为 UTF-8 后上传。'],
  [/宏|外部数据|嵌入对象/, '文件含宏或外部内容，请移除后上传。'],
  [/超时|超过 \d+ 秒/, '读取超时，请拆分文件后重试。'],
  [/过大|过多|资源限制/, '文件内容太大，请拆分后上传。'],
  [/中断/, '读取已中断，请重试。'],
  [/转换.*不可用|转换.*监测失败|进程未返回/, '暂时没读出来，请重试。'],
  [/格式|扩展名/, '暂时读不了这个格式，请另存为常用格式后上传。'],
  [/重新导出|结构/, '文件没读出来，请重新保存后上传。'],
]

const warningHints: [RegExp, string][] = [
  [/^内容由 .+ 转换为 .+ 后提取/, '图片和复杂排版可能不完整'],
  [/^读取的是转换后的表格；公式保存结果已核对/, ''],
  [/部分内容尚未读取/, '其余内容可按需读取'],
  [/隐藏/, '隐藏的内容未读取'],
  [/前 100 页/, '只读取了前 100 页'],
  [/前 100 张幻灯片/, '只读取了前 100 张幻灯片'],
  [/前 20 个工作表/, '只读取了前 20 个工作表'],
  [/上限|20000 行|8000 字符/, '内容较多，只读了部分'],
  [/合并范围/, '部分合并单元格信息未读取'],
  [/公式.*缺少保存值/, '部分公式没有保存结果'],
  [/无可提取文字/, '部分页面没有文字，可能是扫描件'],
]

function documentHint(extraction: Attachment['extraction']) {
  if (extraction?.visualError) return '图片部分没读到。'
  if (extraction?.hasVisuals && extraction.characters === 0 && extraction.status !== 'failed')
    return ''

  if (extraction?.status === 'failed') {
    const error = extraction.error ?? ''
    return (
      failureHints.find(([pattern]) => pattern.test(error))?.[1] ||
      error ||
      '文件没读出来，请重试或重新保存后上传。'
    )
  }
  if (!extraction || !['ready', 'partial'].includes(extraction.status)) return ''
  const hints = (extraction.warnings ?? []).map((warning) =>
    (warningHints.find(([pattern]) => pattern.test(warning))?.[1] ?? warning).replace(
      /[。；]+$/,
      '',
    ),
  )
  const summary = [...new Set(hints.filter(Boolean))].join('；')
  return summary ? `${summary}。` : extraction.status === 'partial' ? '部分内容未能读取。' : ''
}

export function DocumentCard({
  attachment,
  own,
  refresh,
  compact = false,
}: {
  attachment: Attachment
  own: boolean
  refresh: () => void
  compact?: boolean
}) {
  const [pdf, setPdf] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  const extraction = attachment.extraction
  const hint = documentHint(extraction)
  return (
    <div
      className={`${cardStyles.card} ${cardStyles.row} ${documentsStyles['document-card']}`}
      data-compact={compact}
    >
      <span className={cardStyles.icon} aria-hidden="true">
        <FileText size={24} />
      </span>
      <div className={cardStyles.content}>
        <strong className={cardStyles.title}>{attachment.name}</strong>
        <div className={documentsStyles['document-meta']}>
          <p className={cardStyles.meta}>
            {[
              attachment.name.split('.').pop()?.toUpperCase(),
              fileSize(attachment.size),
              extractionStatus(extraction),
            ]
              .filter(Boolean)
              .join(' · ')}
          </p>
          <div
            className={`${layoutStyles['card-actions']} ${documentsStyles['slot-card-actions']}`}
          >
            {attachment.mime === 'application/pdf' && (
              <button
                type="button"
                className={`${controlsStyles['text-button']}`}
                onClick={() => setPdf(true)}
              >
                查看原页
              </button>
            )}
            <a href={attachment.url} download={attachment.name}>
              <Download size={14} />
              下载原文件
            </a>
            {['pending', 'processing'].includes(extraction?.status ?? '') && (
              <button type="button" className={controlsStyles['text-button']} onClick={refresh}>
                刷新状态
              </button>
            )}
            {own && extraction?.status === 'failed' && (
              <BusyButton
                type="button"
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
        </div>
        {hint && <p className={documentsStyles['document-warning']}>{hint}</p>}
        <ErrorNotice>{error}</ErrorNotice>
      </div>
      {pdf && (
        <PdfPreview name={attachment.name} url={attachment.url} onClose={() => setPdf(false)} />
      )}
    </div>
  )
}

function DocumentPreview({
  attachmentId,
  workRevision,
  revision,
  name,
  ordinal = 0,
  onClose,
}: {
  attachmentId: string
  workRevision?: number
  revision?: number
  name: string
  ordinal?: number
  onClose: () => void
}) {
  const [starts, setStarts] = useState([ordinal])
  const start = starts[starts.length - 1]
  const { data, error, refresh } = useResource<ExtractionPage>(
    documentExtractionPath(attachmentId, start, revision, workRevision),
  )
  return (
    <Modal title={name} onClose={onClose}>
      <div className={documentsStyles['document-preview']}>
        <ErrorNotice retry={refresh}>{error}</ErrorNotice>
        {data && !error && (
          <>
            <p className={`${utilitiesStyles['muted']} ${utilitiesStyles['small-text']}`}>
              {[
                data.attachment.extraction?.scope ?? '提取文字',
                extractionStatus(data.attachment.extraction),
              ]
                .filter(Boolean)
                .join(' · ')}
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
              <button
                type="button"
                disabled={starts.length === 1}
                onClick={() => setStarts(starts.slice(0, -1))}
              >
                上一组
              </button>
              <span className={`${utilitiesStyles['muted']} ${utilitiesStyles['small-text']}`}>
                分段 {start + 1}–{start + data.items.length}
              </span>
              <button
                type="button"
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
  if (!citations.length) return null
  return (
    <details className={documentsStyles['document-citations']}>
      <summary>
        <FileText size={14} />
        <span>引用文件 · {citations.length}</span>
        <ChevronDown size={14} />
      </summary>
      {citations.map((citation, index) => (
        <button
          type="button"
          className={`${controlsStyles['text-button']}`}
          key={`${citation.attachmentId}:${citation.previewUrl ?? citation.ordinal}`}
          onClick={() => setSelected(citation)}
        >
          〔{index + 1}〕{citation.name} · {citation.location}
        </button>
      ))}
      {selected &&
        currentCitation(citations, selected) &&
        (selected.sourceKind === 'table' ? (
          <Modal title={selected.name} onClose={() => setSelected(null)}>
            <div className={documentsStyles['document-preview']}>
              <p>{selected.location}</p>
              {selected.rowCount !== null && (
                <p>本次读取的行数：{selected.rowCount}（包含空行）。</p>
              )}
              <p>
                {selected.sampleRows.length
                  ? `已返回的样本：第 ${selected.sampleRows.join('、')} 行。`
                  : '本次仅返回表格统计，没有返回行样本。'}
                {selected.sampleTruncated && '其余行未作为样本展示。'}
              </p>
              <a href={selected.contentUrl} download className={controlsStyles['text-button']}>
                <Download size={14} /> 下载原文件
              </a>
            </div>
          </Modal>
        ) : selected.previewUrl ? (
          <Modal
            title={`${selected.name} · ${selected.location}`}
            onClose={() => setSelected(null)}
          >
            <img
              src={selected.previewUrl}
              alt={selected.location}
              style={{ maxWidth: '100%', height: 'auto' }}
            />
          </Modal>
        ) : (
          <DocumentPreview
            key={`${selected.attachmentId}:${selected.ordinal}`}
            attachmentId={selected.attachmentId}
            revision={selected.revision}
            ordinal={selected.ordinal}
            name={selected.name}
            onClose={() => setSelected(null)}
          />
        ))}
    </details>
  )
}
