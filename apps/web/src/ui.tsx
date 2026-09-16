import { useEffect, useLayoutEffect, useRef, useState, useContext, useMemo } from 'react'
import type { ReactNode, RefObject, TextareaHTMLAttributes } from 'react'
import { Clock3, MoreHorizontal, X } from 'lucide-react'
import { Link } from 'react-router'
import { ApiError, useRetryWait } from './api'
import { Workspace } from './workspace'
import { captureDiagnostics, copyText, diagnosticText } from './diagnostics'

export function ErrorNotice({
  children,
  retry,
}: {
  children: ReactNode | Error
  retry?: () => void
}) {
  const workspace = useContext(Workspace)
  const [copied, setCopied] = useState('')
  const wait = useRetryWait(children)
  const failure = children instanceof ApiError ? children : null
  const fallback = useMemo(
    () => (children instanceof ApiError ? children.diagnostics : captureDiagnostics()),
    [children],
  )
  if (!children || failure?.category === 'cancelled') return null
  const diagnostics = failure?.diagnostics ?? fallback
  return (
    <div className="notice error" role="alert">
      <span>{children instanceof Error ? children.message : children}</span>
      {failure?.requestId && <small className="request-id">请求编号：{failure.requestId}</small>}
      <div className="notice-actions">
        {retry && (!failure || failure.retryable) && (
          <button disabled={wait > 0} onClick={retry}>
            {wait ? `${wait} 秒后重试` : '重试'}
          </button>
        )}
        {workspace && (
          <Link to="/settings/support" state={{ diagnostics }}>
            问题反馈
          </Link>
        )}
        <button
          type="button"
          onClick={() =>
            void copyText(diagnosticText(diagnostics)).then(
              () => setCopied('已复制诊断摘要'),
              () => setCopied('复制失败，请打开问题反馈查看并选择摘要。'),
            )
          }
        >
          复制诊断摘要
        </button>
      </div>
      {copied && <small role="status">{copied}</small>}
    </div>
  )
}
export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      <p>{children}</p>
    </div>
  )
}
function resizeTextarea(node: HTMLTextAreaElement | null) {
  if (!node) return
  node.style.height = 'auto'
  const style = getComputedStyle(node)
  const border = parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth)
  const maximum = parseFloat(style.maxHeight) || 280
  node.style.height = `${Math.min(node.scrollHeight + border, maximum)}px`
  node.style.overflowY = node.scrollHeight + border > maximum ? 'auto' : 'hidden'
}
export function AutoTextarea({
  value,
  defaultValue,
  className = '',
  rows = 2,
  elementRef,
  onInput,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & {
  elementRef?: RefObject<HTMLTextAreaElement | null>
}) {
  const local = useRef<HTMLTextAreaElement>(null)
  const ref = elementRef ?? local
  useLayoutEffect(() => resizeTextarea(ref.current), [value, defaultValue, ref])
  useLayoutEffect(() => {
    const node = ref.current
    if (!node) return
    let width = node.clientWidth
    const observer = new ResizeObserver(() => {
      if (node.clientWidth !== width) {
        width = node.clientWidth
        resizeTextarea(node)
      }
    })
    observer.observe(node)
    return () => observer.disconnect()
  }, [ref])
  return (
    <textarea
      {...props}
      ref={ref}
      value={value}
      defaultValue={defaultValue}
      rows={rows}
      className={`auto-textarea ${className}`}
      onInput={(event) => {
        resizeTextarea(event.currentTarget)
        onInput?.(event)
      }}
    />
  )
}
export function Modal({
  title,
  children,
  onClose,
}: {
  title: string
  children: ReactNode
  onClose: () => void
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const dialog = ref.current!
    const previous = document.activeElement as HTMLElement
    dialog.showModal()
    return () => {
      dialog.close()
      previous?.focus()
    }
  }, [])
  return (
    <dialog
      ref={ref}
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="dialog-content">
        <header>
          <h2>{title}</h2>
          <button type="button" aria-label="关闭" className="icon-button" onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <div className="dialog-body">{children}</div>
      </div>
    </dialog>
  )
}
export function Actions({ children, label = '更多操作' }: { children: ReactNode; label?: string }) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const popup = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    if (!open || !popup.current) return
    const position = () => {
      if (!popup.current) return
      const viewport = window.visualViewport
      const bottom = viewport ? viewport.offsetTop + viewport.height : window.innerHeight
      popup.current.classList.remove('above')
      popup.current.classList.toggle(
        'above',
        popup.current.getBoundingClientRect().bottom > bottom - 16,
      )
    }
    position()
    window.visualViewport?.addEventListener('resize', position)
    return () => window.visualViewport?.removeEventListener('resize', position)
  }, [open])
  useEffect(() => {
    if (!open) return
    const close = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [open])
  return (
    <div
      ref={root}
      className="action-menu"
      onPointerLeave={(e) => {
        if (e.pointerType === 'mouse' && !root.current?.querySelector(':focus-visible'))
          setOpen(false)
      }}
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          setOpen(false)
          trigger.current?.focus()
        }
      }}
    >
      <button
        ref={trigger}
        className="icon-button"
        aria-label={label}
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen(!open)}
      >
        <MoreHorizontal size={19} />
      </button>
      {open && (
        <div
          ref={popup}
          className="popover"
          role="menu"
          onClick={() => {
            setOpen(false)
            trigger.current?.focus()
          }}
        >
          <div className="popover-items">{children}</div>
        </div>
      )}
    </div>
  )
}
export function BusyButton({
  busy,
  children,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { busy: boolean }) {
  return (
    <button {...props} disabled={busy || props.disabled}>
      {busy ? '处理中…' : children}
    </button>
  )
}
export const statusLabel = (status: string) =>
  ({
    in_progress: '进行中',
    blocked: '有阻碍',
    done: '已完成',
    pending: '待确认',
    confirmed: '已确认',
    ignored: '已忽略',
  })[status] ?? status
export function Status({ value }: { value: string }) {
  return <span className={`status ${value}`}>{statusLabel(value)}</span>
}

export function ConflictRecovery<T>({
  load,
  render,
  keep,
  replace,
}: {
  load: () => Promise<T>
  render: (latest: T) => ReactNode
  keep: (latest: T) => void
  replace: (latest: T) => void
}) {
  const [latest, setLatest] = useState<T | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  return (
    <section className="conflict-recovery">
      <BusyButton
        type="button"
        busy={busy}
        onClick={async () => {
          setBusy(true)
          try {
            setLatest(await load())
            setError('')
          } catch (e) {
            setError(e as Error)
          } finally {
            setBusy(false)
          }
        }}
      >
        读取最新版本
      </BusyButton>
      {error && <ErrorNotice>{error}</ErrorNotice>}
      {latest && (
        <div className="panel">
          <h3>服务端最新内容</h3>
          {render(latest)}
          <p className="muted">
            核对后选择如何继续。保留当前输入时，之后保存会替换这里显示的内容；已有提交历史仍保留。
          </p>
          <div className="card-actions">
            <button
              type="button"
              onClick={() => {
                keep(latest)
                setLatest(null)
              }}
            >
              保留当前输入，继续编辑
            </button>
            <button
              type="button"
              onClick={() => {
                replace(latest)
                setLatest(null)
              }}
            >
              使用最新内容
            </button>
          </div>
        </div>
      )}
    </section>
  )
}

export function TimeField({
  value,
  onChange,
  required,
}: {
  value: string
  onChange: (value: string) => void
  required?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [choice, setChoice] = useState('09:00')
  const show = () => {
    setChoice(/^\d{2}:\d{2}$/.test(value) ? value : '09:00')
    setOpen(true)
  }
  return (
    <span className="time-field">
      <input
        value={value}
        required={required}
        placeholder="时:分"
        inputMode="numeric"
        pattern="([01][0-9]|2[0-3]):[0-5][0-9]"
        onChange={(e) => onChange(e.target.value)}
        onClick={show}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') {
            e.preventDefault()
            show()
          }
        }}
      />
      <button type="button" className="icon-button" aria-label="选择时间" onClick={show}>
        <Clock3 size={17} />
      </button>
      {open && (
        <Modal title="选择时间" onClose={() => setOpen(false)}>
          <div className="time-picker">
            <label>
              时
              <select
                value={choice.slice(0, 2)}
                onChange={(e) => setChoice(e.target.value + choice.slice(2))}
              >
                {Array.from({ length: 24 }, (_, n) => String(n).padStart(2, '0')).map((n) => (
                  <option key={n}>{n}</option>
                ))}
              </select>
            </label>
            <span>:</span>
            <label>
              分
              <select
                value={choice.slice(3)}
                onChange={(e) => setChoice(choice.slice(0, 3) + e.target.value)}
              >
                {Array.from({ length: 60 }, (_, n) => String(n).padStart(2, '0')).map((n) => (
                  <option key={n}>{n}</option>
                ))}
              </select>
            </label>
          </div>
          <div className="form-actions">
            <button
              type="button"
              onClick={() => {
                onChange('')
                setOpen(false)
              }}
            >
              清空
            </button>
            <button
              type="button"
              className="primary"
              onClick={() => {
                onChange(choice)
                setOpen(false)
              }}
            >
              确定
            </button>
          </div>
        </Modal>
      )}
    </span>
  )
}
