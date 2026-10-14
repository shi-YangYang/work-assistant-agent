import controlsStyles from '../../styles/controls.module.css'
import styles from '../../styles/patterns/Modal.module.css'
import { X } from 'lucide-react'
import type { KeyboardEventHandler, ReactNode, RefObject } from 'react'
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
  closeDisabled = false,
  descriptionId,
  initialFocusRef,
}: {
  title: string
  className?: string
  bodyClassName?: string
  variant?: 'default' | 'media' | 'drawer'
  children: ReactNode
  onClose: () => void
  onKeyDown?: KeyboardEventHandler<HTMLDialogElement>
  closeDisabled?: boolean
  descriptionId?: string
  initialFocusRef?: RefObject<HTMLElement | null>
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const dialog = ref.current!
    const previous = document.activeElement as HTMLElement
    dialog.showModal()
    initialFocusRef?.current?.focus()
    return () => {
      dialog.close()
      previous?.focus()
    }
  }, [initialFocusRef])
  return (
    <ErrorNoticeScope priority={100} isolate>
      <dialog
        aria-label={title}
        aria-describedby={descriptionId}
        className={`${styles['dialog']} ${variant === 'media' ? styles['media-dialog'] : variant === 'drawer' ? styles['team-detail-drawer'] : ''} ${className}`}
        ref={ref}
        onKeyDown={onKeyDown}
        onCancel={(event) => {
          event.preventDefault()
          if (!closeDisabled) onClose()
        }}
        onClick={(e) => {
          if (e.target === e.currentTarget && !closeDisabled) onClose()
        }}
      >
        <div className={styles['dialog-content']}>
          <header>
            <h2>{title}</h2>
            <button
              type="button"
              aria-label="关闭"
              disabled={closeDisabled}
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
