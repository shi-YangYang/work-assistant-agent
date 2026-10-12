import type { AssistantActivityState } from '@web/api/assistant-activity'
import { Menu } from 'lucide-react'
import { useState, type RefObject } from 'react'
import controls from '@web/styles/controls.module.css'
import { NoriaPet } from './NoriaPet'
import { NoriaAppearanceDialog } from './NoriaAppearanceDialog'
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
          aria-label="Noria 外观"
          title="Noria 外观"
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={(event) => {
            // Safari does not focus buttons on pointer clicks; Modal needs the
            // trigger as its return target when the dialog closes.
            event.currentTarget.focus()
            setOpen(true)
          }}
        >
          <NoriaPet animate={animate && !open} working={activity === 'working'} />
          <span className={styles.name}>Noria</span>
          {activity !== 'idle' && (
            <span className={styles.status} role="status">
              {activity === 'working' ? '努力工作中' : '状态待同步'}
            </span>
          )}
        </button>
      </div>
      {open && <NoriaAppearanceDialog onClose={() => setOpen(false)} />}
    </>
  )
}
