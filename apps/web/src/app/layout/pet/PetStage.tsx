import type { AssistantActivityState } from '@web/api/assistant-activity'
import { CloudOff, Menu, Wrench } from 'lucide-react'
import { useState, type RefObject } from 'react'
import controls from '@web/styles/controls.module.css'
import { NoriaPet } from './NoriaPet'
import { NoriaAppearanceDialog } from './NoriaAppearanceDialog'
import { useNotificationSummary } from '@web/features/notifications/hooks/useNotificationSummary'
import styles from './PetStage.module.css'

export function PetStage({
  animate,
  activity = 'idle',
  navTriggerRef,
  expandedNav,
  setExpandedNav,
}: {
  animate: boolean
  activity?: AssistantActivityState
  navTriggerRef: RefObject<HTMLButtonElement | null>
  expandedNav: boolean
  setExpandedNav: (expanded: boolean) => void
}) {
  const [open, setOpen] = useState(false)
  const unread = useNotificationSummary()?.data?.totalUnread ?? 0
  const label = unread > 0 ? `Noria，${unread} 条未读通知` : 'Noria'
  return (
    <>
      <div className={styles.stage}>
        <button
          type="button"
          ref={navTriggerRef}
          className={`${controls['icon-button']} ${styles.navigation}`}
          aria-label={expandedNav ? '收起导航' : '展开导航'}
          aria-expanded={expandedNav}
          aria-controls="sidebar-navigation"
          onClick={() => setExpandedNav(!expandedNav)}
        >
          <Menu size={19} />
        </button>
        <button
          type="button"
          className={styles.trigger}
          aria-label={label}
          title={label}
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={(event) => {
            // Safari does not focus buttons on pointer clicks; Modal needs the
            // trigger as its return target when the dialog closes.
            event.currentTarget.focus()
            setOpen(true)
          }}
        >
          <span className={styles.avatar}>
            <NoriaPet animate={animate && !open} working={activity === 'working'} />
            {unread > 0 && (
              <span className={styles.unread} aria-hidden="true">
                {unread > 99 ? '99+' : unread}
              </span>
            )}
          </span>
          <span className={styles.bubble}>
            <span className={styles.name}>Noria</span>
            {activity !== 'idle' && (
              <span className={styles.status} role="status">
                {activity === 'working' ? (
                  <Wrench size={12} aria-hidden="true" />
                ) : (
                  <CloudOff size={12} aria-hidden="true" />
                )}
                {activity === 'working' ? '努力工作中' : '状态待同步'}
              </span>
            )}
          </span>
        </button>
      </div>
      {open && <NoriaAppearanceDialog onClose={() => setOpen(false)} />}
    </>
  )
}
