import type { ReasoningOption } from '@paa/api-contracts'
import { Check, ChevronDown } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Modal } from '@web/components/overlays/Modal'
import { useMobileComposerControl } from '../../../hooks/composer/useMobileComposerPanel'
import styles from './ReasoningEffortPicker.module.css'

export function ReasoningEffortPicker({
  options,
  selected,
  saving,
  disabled,
  onChange,
}: {
  options: ReasoningOption[]
  selected: ReasoningOption | null
  saving: boolean
  disabled?: boolean
  onChange: (id: string) => void
}) {
  const { mobile, available, activate, deactivate } = useMobileComposerControl('reasoning')
  const [requestedOpen, setOpen] = useState(false)
  const [position, setPosition] = useState({ left: 0, bottom: 0 })
  const [previousMobile, setPreviousMobile] = useState(mobile)
  const trigger = useRef<HTMLButtonElement>(null)
  const restoreAfterSave = useRef(false)
  const menu = useRef<HTMLDivElement>(null)
  const selectedItem = useRef<HTMLButtonElement>(null)
  const items = useRef<(HTMLButtonElement | null)[]>([])
  const id = useId()
  useEffect(() => {
    if (saving || !restoreAfterSave.current) return
    restoreAfterSave.current = false
    // Disabling the focused trigger during a save blurs it in the browser.
    // Restore keyboard position only if the user has not focused another control.
    if (!disabled && document.activeElement === document.body) trigger.current?.focus()
  }, [saving, disabled])
  const open = available && requestedOpen && !saving && !disabled
  const close = (restore = true) => {
    setOpen(false)
    if (restore) {
      deactivate()
      trigger.current?.focus()
    }
  }
  if (previousMobile !== mobile || (!available && requestedOpen)) {
    setPreviousMobile(mobile)
    setOpen(false)
  }
  const show = () => {
    activate()
    setOpen(true)
    if (mobile) return
    const rect = trigger.current?.getBoundingClientRect()
    if (rect)
      setPosition({
        left: Math.max(12, Math.min(rect.right - 160, window.innerWidth - 172)),
        bottom: window.innerHeight - rect.top + 8,
      })
  }
  useEffect(() => {
    if (!open || mobile) return
    items.current[
      Math.max(
        0,
        options.findIndex((item) => item.effort === selected?.effort),
      )
    ]?.focus()
    const outside = (event: PointerEvent) => {
      if (
        !trigger.current?.contains(event.target as Node) &&
        !menu.current?.contains(event.target as Node)
      ) {
        setOpen(false)
        deactivate()
      }
    }
    const resize = () => {
      setOpen(false)
      deactivate()
    }
    document.addEventListener('pointerdown', outside)
    window.addEventListener('resize', resize)
    window.visualViewport?.addEventListener('resize', resize)
    return () => {
      document.removeEventListener('pointerdown', outside)
      window.removeEventListener('resize', resize)
      window.visualViewport?.removeEventListener('resize', resize)
    }
  }, [open, mobile, options, selected?.effort, deactivate])
  if (!options.length || !selected) return null
  const choices = (
    <div
      ref={menu}
      id={id}
      role="menu"
      data-composer-layer="reasoning"
      aria-label="思考强度"
      className={styles.menu}
      data-inline={mobile}
      style={mobile ? undefined : position}
      onBlur={(event) => {
        if (!mobile && !event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setOpen(false)
          deactivate()
        }
      }}
      onKeyDown={(event) => {
        if (event.key === 'Escape' && !event.nativeEvent.isComposing) {
          event.preventDefault()
          event.stopPropagation()
          close()
          return
        }
        const index = items.current.indexOf(document.activeElement as HTMLButtonElement)
        const next =
          event.key === 'ArrowDown'
            ? (index + 1) % options.length
            : event.key === 'ArrowUp'
              ? (index + options.length - 1) % options.length
              : event.key === 'Home'
                ? 0
                : event.key === 'End'
                  ? options.length - 1
                  : null
        if (next !== null) {
          event.preventDefault()
          items.current[next]?.focus()
        }
      }}
    >
      {options.map((option, index) => (
        <button
          key={option.effort}
          ref={(element) => {
            items.current[index] = element
            if (selected.effort === option.effort) selectedItem.current = element
          }}
          type="button"
          role="menuitemradio"
          aria-checked={selected.effort === option.effort}
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => {
            restoreAfterSave.current = true
            close()
            onChange(option.effort)
          }}
        >
          <span>{option.effort}</span>
          {selected.effort === option.effort && <Check size={15} aria-hidden="true" />}
        </button>
      ))}
    </div>
  )
  return (
    <>
      <button
        ref={trigger}
        type="button"
        className={styles.trigger}
        data-panel={mobile}
        title={`思考强度：${selected.effort}，适用于下一条消息`}
        aria-label={`思考强度：${selected.effort}`}
        aria-haspopup={mobile ? 'dialog' : 'menu'}
        aria-expanded={open}
        aria-controls={open && !mobile ? id : undefined}
        aria-busy={saving}
        disabled={saving || disabled}
        onClick={() => (open ? close() : show())}
        onKeyDown={(event) => {
          if (['ArrowUp', 'ArrowDown'].includes(event.key)) {
            event.preventDefault()
            show()
          }
        }}
      >
        {mobile && <span className={styles['panel-title']}>思考强度</span>}
        <span>{selected.effort}</span>
        <ChevronDown size={12} aria-hidden="true" />
      </button>
      {open &&
        (mobile ? (
          <Modal
            title="思考强度"
            className={styles['mobile-dialog']}
            initialFocusRef={selectedItem}
            onClose={() => close()}
            onKeyDown={(event) => {
              if (event.key === 'Escape' && !event.nativeEvent.isComposing) {
                event.preventDefault()
                event.stopPropagation()
                close()
              }
            }}
          >
            {choices}
          </Modal>
        ) : (
          createPortal(choices, document.body)
        ))}
    </>
  )
}
