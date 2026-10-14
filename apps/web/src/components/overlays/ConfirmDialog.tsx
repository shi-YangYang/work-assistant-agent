import { useId, useRef, type ReactNode } from 'react'
import { BusyButton } from '../actions/BusyButton'
import { ErrorNoticeView } from '../feedback/ErrorNotice'
import { Modal } from './Modal'
import controls from '../../styles/controls.module.css'
import styles from './ConfirmDialog.module.css'

export function ConfirmDialog({
  title,
  children,
  confirmLabel = '确认',
  cancelLabel = '取消',
  danger = false,
  busy = false,
  confirmDisabled = false,
  error = '',
  onConfirm,
  onClose,
}: {
  title: string
  children: ReactNode
  confirmLabel?: string
  cancelLabel?: string
  danger?: boolean
  busy?: boolean
  confirmDisabled?: boolean
  error?: Error | string
  onConfirm: () => void
  onClose: () => void
}) {
  const descriptionId = useId()
  const cancelRef = useRef<HTMLButtonElement>(null)
  return (
    <Modal
      title={title}
      descriptionId={descriptionId}
      className={styles.confirm}
      bodyClassName={styles.body}
      closeDisabled={busy}
      initialFocusRef={cancelRef}
      onClose={onClose}
    >
      <div id={descriptionId} className={styles.description}>
        {children}
      </div>
      <ErrorNoticeView>{error}</ErrorNoticeView>
      <div className={styles.actions}>
        <button type="button" ref={cancelRef} disabled={busy} onClick={onClose}>
          {cancelLabel}
        </button>
        <BusyButton
          type="button"
          className={danger ? controls.danger : controls.primary}
          busy={busy}
          disabled={confirmDisabled}
          onClick={() => {
            if (!busy && !confirmDisabled) onConfirm()
          }}
        >
          {confirmLabel}
        </BusyButton>
      </div>
    </Modal>
  )
}
