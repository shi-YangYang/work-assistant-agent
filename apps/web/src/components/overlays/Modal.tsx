import controlsStyles from '../../styles/controls.module.css'
import styles from '../../styles/patterns/Modal.module.css'
import { X } from 'lucide-react'
import type { KeyboardEventHandler, ReactNode } from 'react'
import { useEffect, useRef } from 'react'
import { ErrorNoticeOutlet, ErrorNoticeScope } from '../feedback/ErrorNoticeScope'

export function Modal({
  title,
  children,
  onClose,
  className = '',
  bodyClassName = '',
  variant = 'default',
  onKeyDown,
}: {
  title: string
  className?: string
  bodyClassName?: string
  variant?: 'default' | 'media' | 'drawer'
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
    <ErrorNoticeScope priority={100} isolate>
      <dialog
        aria-label={title}
        className={`${styles['dialog']} ${variant === 'media' ? styles['media-dialog'] : variant === 'drawer' ? styles['team-detail-drawer'] : ''} ${className}`}
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
        <div className={styles['dialog-content']}>
          <header>
            <h2>{title}</h2>
            <button
              type="button"
              aria-label="关闭"
              className={controlsStyles['icon-button']}
              onClick={onClose}
            >
              <X size={18} />
            </button>
          </header>
          <div className={`${styles['dialog-body']} ${bodyClassName}`}>
            <ErrorNoticeOutlet label={`${title}提示`} className={styles['dialog-notice']} />
            {children}
          </div>
        </div>
      </dialog>
    </ErrorNoticeScope>
  )
}
