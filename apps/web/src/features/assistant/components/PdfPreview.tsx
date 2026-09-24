import mediaPreviewStyles from '../styles/media-preview.module.css'
import { isCancelled } from '@web/api/client'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Modal } from '@web/components/Modal'
import { readAttachmentBytes } from '@web/features/assistant/api/requests'
import { ChevronLeft, ChevronRight, Download, Expand, ZoomIn, ZoomOut } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

type PDFDocument = import('pdfjs-dist').PDFDocumentProxy

export function PdfPreview({
  name,
  file,
  url,
  onClose,
}: {
  name: string
  file?: File
  url?: string
  onClose: () => void
}) {
  const [document, setDocument] = useState<PDFDocument | null>(null)
  const [page, setPage] = useState(1)
  const [zoom, setZoom] = useState(1)
  const [width, setWidth] = useState(0)
  const [error, setError] = useState<Error | string>('')
  const [loading, setLoading] = useState(true)
  const [download, setDownload] = useState(url ?? '')
  const canvas = useRef<HTMLCanvasElement>(null)
  const viewport = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const node = viewport.current!
    const observer = new ResizeObserver(() => setWidth(node.clientWidth))
    observer.observe(node)
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    let disposed = false
    let task: import('pdfjs-dist').PDFDocumentLoadingTask | undefined
    const controller = new AbortController()
    const localUrl = file ? URL.createObjectURL(file) : ''
    void (async () => {
      const [pdf, worker, bytes] = await Promise.all([
        import('pdfjs-dist'),
        import('pdfjs-dist/build/pdf.worker.min.mjs?url'),
        file ? file.arrayBuffer() : readAttachmentBytes(url, { signal: controller.signal }),
      ])
      if (disposed) return
      if (localUrl) setDownload(localUrl)
      pdf.GlobalWorkerOptions.workerSrc = worker.default
      task = pdf.getDocument({
        data: new Uint8Array(bytes),
        cMapUrl: '/pdfjs/cmaps/',
        cMapPacked: true,
        standardFontDataUrl: '/pdfjs/standard_fonts/',
        wasmUrl: '/pdfjs/wasm/',
        iccUrl: '/pdfjs/iccs/',
        disableFontFace: true,
        useSystemFonts: false,
      })
      const result = await task.promise
      if (!disposed) setDocument(result)
    })().catch((failure) => {
      if (!disposed && !isCancelled(failure)) {
        setError(
          failure instanceof Error && failure.name === 'ApiError'
            ? failure
            : 'PDF 无法预览，可能已损坏或加密；可下载原文件。',
        )
        setLoading(false)
      }
    })
    return () => {
      disposed = true
      controller.abort()
      void task?.destroy()
      if (localUrl) URL.revokeObjectURL(localUrl)
    }
  }, [file, url])
  useEffect(() => {
    if (!document || !width || !canvas.current) return
    let disposed = false
    let render: import('pdfjs-dist').RenderTask | undefined
    const target = canvas.current
    void document
      .getPage(page)
      .then(async (item) => {
        if (disposed) {
          item.cleanup()
          return
        }
        setLoading(true)
        const base = item.getViewport({ scale: 1 })
        const scale = Math.max(0.1, ((width - 24) / base.width) * zoom)
        const ratio = Math.min(
          window.devicePixelRatio || 1,
          2,
          Math.sqrt(8_000_000 / (base.width * base.height * scale * scale)),
        )
        const view = item.getViewport({ scale: scale * ratio })
        target.width = Math.ceil(view.width)
        target.height = Math.ceil(view.height)
        target.style.width = `${base.width * scale}px`
        target.style.height = `${base.height * scale}px`
        render = item.render({ canvas: target, viewport: view })
        try {
          await render.promise
        } finally {
          item.cleanup()
        }
        if (!disposed) setLoading(false)
      })
      .catch((failure) => {
        if (!disposed && failure?.name !== 'RenderingCancelledException') {
          setError('此页无法显示，可切换其他页面或下载原文件。')
          setLoading(false)
        }
      })
    return () => {
      disposed = true
      render?.cancel()
    }
  }, [document, page, width, zoom])
  return (
    <Modal title={name} variant="media" onClose={onClose}>
      <div className={mediaPreviewStyles['media-preview']}>
        <div className={mediaPreviewStyles['preview-toolbar']}>
          <div>
            <button
              aria-label="上一页"
              disabled={!document || page === 1}
              onClick={() => {
                setError('')
                setPage(page - 1)
              }}
            >
              <ChevronLeft size={18} />
            </button>
            <label className={mediaPreviewStyles['pdf-page-label']}>
              <input
                aria-label="PDF 页码"
                type="number"
                min={1}
                max={document?.numPages ?? 1}
                value={page}
                disabled={!document}
                onChange={(event) => {
                  setError('')
                  setPage(
                    Math.max(1, Math.min(document?.numPages ?? 1, Number(event.target.value) || 1)),
                  )
                }}
              />{' '}
              / {document?.numPages ?? '—'}
            </label>
            <button
              aria-label="下一页"
              disabled={!document || page === document.numPages}
              onClick={() => {
                setError('')
                setPage(page + 1)
              }}
            >
              <ChevronRight size={18} />
            </button>
          </div>
          <div>
            <button
              aria-label="缩小页面"
              disabled={zoom <= 0.5}
              onClick={() => setZoom(Math.max(0.5, zoom / 1.25))}
            >
              <ZoomOut size={18} />
            </button>
            <button
              aria-label="放大页面"
              disabled={zoom >= 3}
              onClick={() => setZoom(Math.min(3, zoom * 1.25))}
            >
              <ZoomIn size={18} />
            </button>
            <button aria-label="适应宽度" title="适应宽度" onClick={() => setZoom(1)}>
              <Expand size={18} />
            </button>
            {download && (
              <a
                className={mediaPreviewStyles['preview-download']}
                href={download}
                download={name}
                aria-label="下载 PDF 原文件"
              >
                <Download size={18} />
              </a>
            )}
          </div>
        </div>
        <ErrorNotice>{error}</ErrorNotice>
        <div className={mediaPreviewStyles['pdf-viewport']} ref={viewport}>
          {loading && (
            <p role="status" className={mediaPreviewStyles['preview-loading']}>
              正在载入页面…
            </p>
          )}
          <canvas ref={canvas} aria-label={`第 ${page} 页`} />
        </div>
      </div>
    </Modal>
  )
}
