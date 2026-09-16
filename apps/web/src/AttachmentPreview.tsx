import { useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, Download, Expand, ZoomIn, ZoomOut } from 'lucide-react'
import { api, isCancelled } from './api'
import { ErrorNotice, Modal } from './ui'

export type PreviewImage = {
  id: string
  name: string
  src?: string
  original: string
  prepare?: () => Promise<string>
  warnings?: string[]
}
export function ImageGallery({
  images,
  initial,
  onClose,
}: {
  images: PreviewImage[]
  initial: number
  onClose: () => void
}) {
  const [index, setIndex] = useState(initial)
  const [retry, setRetry] = useState(0)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [error, setError] = useState<Error | string>('')
  const [converting, setConverting] = useState(false)
  const [prepared, setPrepared] = useState<Record<string, string>>({})
  const [natural, setNatural] = useState({ width: 0, height: 0 })
  const [size, setSize] = useState({ width: 0, height: 0 })
  const view = useRef<HTMLDivElement>(null)
  const alive = useRef(true)
  const drag = useRef<{ x: number; y: number; pan: typeof pan } | null>(null)
  const item = images[index]
  const src = item?.src ?? prepared[item?.id]
  useEffect(() => {
    alive.current = true
    const node = view.current!
    const observer = new ResizeObserver(() =>
      setSize({ width: node.clientWidth, height: node.clientHeight }),
    )
    observer.observe(node)
    return () => {
      alive.current = false
      observer.disconnect()
    }
  }, [])
  function reset() {
    setZoom(1)
    setPan({ x: 0, y: 0 })
    drag.current = null
  }
  function choose(next: number) {
    const bounded = Math.max(0, Math.min(images.length - 1, next))
    if (bounded === index || converting) return
    setIndex(bounded)
    setError('')
    setNatural({ width: 0, height: 0 })
    reset()
  }
  const fit = natural.width
    ? Math.min(1, (size.width - 24) / natural.width, (size.height - 24) / natural.height)
    : 1
  return (
    <Modal
      title={item?.name ?? '图片预览'}
      className="media-dialog"
      onClose={onClose}
      onKeyDown={(event) => {
        if (event.key === 'ArrowLeft') {
          event.preventDefault()
          choose(index - 1)
        }
        if (event.key === 'ArrowRight') {
          event.preventDefault()
          choose(index + 1)
        }
      }}
    >
      <div className="media-preview">
        <div className="preview-toolbar">
          <div>
            <button
              aria-label="上一张"
              disabled={index === 0 || converting}
              onClick={() => choose(index - 1)}
            >
              <ChevronLeft size={18} />
            </button>
            <span>
              {index + 1} / {images.length}
            </span>
            <button
              aria-label="下一张"
              disabled={index === images.length - 1 || converting}
              onClick={() => choose(index + 1)}
            >
              <ChevronRight size={18} />
            </button>
          </div>
          <div>
            <button
              aria-label="缩小图片"
              disabled={zoom <= 0.5}
              onClick={() => setZoom(Math.max(0.5, zoom / 1.25))}
            >
              <ZoomOut size={18} />
            </button>
            <span>{Math.round(zoom * 100)}%</span>
            <button
              aria-label="放大图片"
              disabled={zoom >= 8}
              onClick={() => setZoom(Math.min(8, zoom * 1.25))}
            >
              <ZoomIn size={18} />
            </button>
            <button aria-label="适应窗口" title="适应窗口" onClick={reset}>
              <Expand size={18} />
            </button>
            {item && (
              <a
                className="preview-download"
                href={item.original}
                download={item.name}
                aria-label="下载原图片"
              >
                <Download size={18} />
              </a>
            )}
          </div>
        </div>
        <ErrorNotice
          retry={
            src
              ? () => {
                  setError('')
                  setNatural({ width: 0, height: 0 })
                  setRetry((value) => value + 1)
                }
              : undefined
          }
        >
          {error}
        </ErrorNotice>
        {item?.warnings?.map((warning) => (
          <p className="document-warning" key={warning}>
            {warning}
          </p>
        ))}
        <div
          className="image-viewport"
          ref={view}
          onPointerDown={(event) => {
            if (!src) return
            event.currentTarget.setPointerCapture(event.pointerId)
            drag.current = { x: event.clientX, y: event.clientY, pan }
          }}
          onPointerMove={(event) => {
            if (drag.current)
              setPan({
                x: drag.current.pan.x + event.clientX - drag.current.x,
                y: drag.current.pan.y + event.clientY - drag.current.y,
              })
          }}
          onPointerUp={() => {
            drag.current = null
          }}
          onPointerCancel={() => {
            drag.current = null
          }}
        >
          {src && !natural.width && !error && (
            <p className="preview-loading" role="status">
              正在载入图片…
            </p>
          )}
          {src ? (
            <img
              key={`${src}:${retry}`}
              src={src}
              alt={item.name}
              draggable={false}
              style={{
                width: natural.width ? natural.width * fit * zoom : undefined,
                height: natural.height ? natural.height * fit * zoom : undefined,
                transform: `translate(${pan.x}px, ${pan.y}px)`,
              }}
              onLoad={(event) =>
                setNatural({
                  width: event.currentTarget.naturalWidth,
                  height: event.currentTarget.naturalHeight,
                })
              }
              onError={() => setError('图片预览不可用，请重试或下载原文件。')}
            />
          ) : (
            <div className="preview-placeholder">
              <p>HEIC／HEIF 图片需要转换后预览</p>
              <button
                disabled={converting}
                onClick={async () => {
                  if (!item?.prepare) return
                  setConverting(true)
                  setError('')
                  try {
                    const url = await item.prepare()
                    if (alive.current) setPrepared((old) => ({ ...old, [item.id]: url }))
                  } catch (failure) {
                    if (alive.current && !isCancelled(failure)) setError(failure as Error)
                  } finally {
                    if (alive.current) setConverting(false)
                  }
                }}
              >
                {converting ? '正在准备…' : '生成预览'}
              </button>
            </div>
          )}
        </div>
      </div>
    </Modal>
  )
}

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
        file
          ? file.arrayBuffer()
          : api<ArrayBuffer>(
              (url ?? '').replace(/^\/api\/v1/, ''),
              { signal: controller.signal },
              'bytes',
            ),
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
    <Modal title={name} className="media-dialog" onClose={onClose}>
      <div className="media-preview">
        <div className="preview-toolbar">
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
            <label className="pdf-page-label">
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
                className="preview-download"
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
        <div className="pdf-viewport" ref={viewport}>
          {loading && (
            <p role="status" className="preview-loading">
              正在载入页面…
            </p>
          )}
          <canvas ref={canvas} aria-label={`第 ${page} 页`} />
        </div>
      </div>
    </Modal>
  )
}
