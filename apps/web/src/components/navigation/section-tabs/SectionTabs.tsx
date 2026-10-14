import type { ComponentProps } from 'react'
import { PanelSection } from '@web/components/content/PanelSection'
import layoutStyles from '../../../styles/layout.module.css'
import styles from './SectionTabs.module.css'

export function SectionTabs<T extends string>({
  scope,
  label,
  tabs,
  selected,
  onChange,
  disabled = false,
}: {
  scope: string
  label: string
  tabs: readonly { id: T; label: string }[]
  selected: T
  onChange: (id: T) => void
  disabled?: boolean
}) {
  return (
    <div className={`${layoutStyles.tabs} ${styles.tablist}`} role="tablist" aria-label={label}>
      {tabs.map((tab, index) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          id={`${scope}-tab-${tab.id}`}
          aria-controls={`${scope}-panel-${tab.id}`}
          aria-selected={selected === tab.id}
          data-active={selected === tab.id}
          tabIndex={selected === tab.id ? 0 : -1}
          disabled={disabled}
          onClick={() => onChange(tab.id)}
          onKeyDown={(event) => {
            let next: number
            if (event.key === 'ArrowRight') next = (index + 1) % tabs.length
            else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length
            else if (event.key === 'Home') next = 0
            else if (event.key === 'End') next = tabs.length - 1
            else return
            event.preventDefault()
            onChange(tabs[next].id)
            const buttons =
              event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]')
            buttons?.[next]?.focus()
          }}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}

export function TabSection({
  tab,
  ...section
}: ComponentProps<typeof PanelSection> & {
  tab?: { scope: string; id: string; selected: string }
}) {
  if (!tab) return <PanelSection {...section} />
  return (
    <div
      role="tabpanel"
      id={`${tab.scope}-panel-${tab.id}`}
      aria-labelledby={`${tab.scope}-tab-${tab.id}`}
      hidden={tab.selected !== tab.id}
      tabIndex={0}
      className={styles.panel}
    >
      {section.status && <p className={styles.status}>{section.status}</p>}
      <div className={`${styles.body} ${section.bodyClassName ?? ''}`}>{section.children}</div>
    </div>
  )
}
