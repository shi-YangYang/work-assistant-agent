import { ThemePicker } from '@web/components/appearance/ThemePicker'
import { Modal } from '@web/components/overlays/Modal'
import { NotificationEntry } from '@web/features/notifications/components/NotificationEntry'
import { NoriaPet } from './NoriaPet'
import styles from './NoriaAppearanceDialog.module.css'

export function NoriaAppearanceDialog({ onClose }: { onClose: () => void }) {
  return (
    <Modal title="Noria" onClose={onClose} className={styles.dialog}>
      <div className={styles.preview}>
        <NoriaPet animate />
        <p>你的 AI 伙伴</p>
      </div>
      <NotificationEntry
        className={styles.notifications}
        labelClassName={styles['notification-label']}
        onNavigate={onClose}
      />
      <h3 className={styles.label}>页面主题</h3>
      <ThemePicker />
    </Modal>
  )
}
