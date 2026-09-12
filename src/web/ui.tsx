import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { MoreHorizontal, X } from 'lucide-react'

export function ErrorNotice({ children, retry }: { children: ReactNode; retry?: () => void }) {
  return children ? (
    <div className="notice error" role="alert">
      <span>{children}</span>
      {retry && <button onClick={retry}>重试</button>}
    </div>
  ) : null
}
export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      <p>{children}</p>
    </div>
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
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="dialog-content">
        <header>
          <h2>{title}</h2>
          <button aria-label="关闭" className="icon-button" onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        {children}
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
    const above =
      popup.current.getBoundingClientRect().bottom >
      window.innerHeight - (window.innerWidth <= 760 ? 80 : 16)
    popup.current.classList.toggle('above', above)
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
          {children}
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
  const [error, setError] = useState('')
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
            setError((e as Error).message)
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
