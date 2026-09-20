import { X } from 'lucide-react'
import type { KeyboardEventHandler, ReactNode } from 'react'
import { useEffect, useRef } from 'react'

export function Modal({
  title,
  children,
  onClose,
  className,
  onKeyDown,
}: {
  title: string
  className?: string
  children: ReactNode
  onClose: () => void
  onKeyDown?: KeyboardEventHandler<HTMLDialogElement>
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
      className={className}
      ref={ref}
      onKeyDown={onKeyDown}
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
