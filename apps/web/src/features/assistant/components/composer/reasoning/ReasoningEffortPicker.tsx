import type { ReasoningOption } from '@paa/api-contracts'
import { Check, ChevronDown } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
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
  const [position, setPosition] = useState<{ left: number; bottom: number } | null>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const restoreAfterSave = useRef(false)
  const menu = useRef<HTMLDivElement>(null)
  const items = useRef<(HTMLButtonElement | null)[]>([])
  const id = useId()
  useEffect(() => {
    if (saving || !restoreAfterSave.current) return
    restoreAfterSave.current = false
    // Disabling the focused trigger during a save blurs it in the browser.
    // Restore keyboard position only if the user has not focused another control.
    if (!disabled && document.activeElement === document.body) trigger.current?.focus()
  }, [saving, disabled])
  const open = !!position && !saving && !disabled
  const close = () => {
    setPosition(null)
    trigger.current?.focus()
  }
  const show = () => {
    const rect = trigger.current?.getBoundingClientRect()
    if (rect)
      setPosition({
        left: Math.max(12, Math.min(rect.right - 160, window.innerWidth - 172)),
        bottom: window.innerHeight - rect.top + 8,
      })
  }
  useEffect(() => {
    if (!open) return
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
      )
        setPosition(null)
    }
    const resize = () => setPosition(null)
    document.addEventListener('pointerdown', outside)
    window.addEventListener('resize', resize)
    return () => {
      document.removeEventListener('pointerdown', outside)
      window.removeEventListener('resize', resize)
    }
  }, [open, options, selected?.effort])
  if (!options.length || !selected) return null
  return (
    <>
      <button
        ref={trigger}
        type="button"
        className={styles.trigger}
        title={`思考强度：${selected.effort}，适用于下一条消息`}
        aria-label={`思考强度：${selected.effort}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
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
        <span>{selected.effort}</span>
        <ChevronDown size={12} aria-hidden="true" />
      </button>
      {open &&
        createPortal(
          <div
            ref={menu}
            id={id}
            role="menu"
            aria-label="思考强度"
            className={styles.menu}
            style={position!}
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as Node | null))
                setPosition(null)
            }}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
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
          </div>,
          document.body,
        )}
    </>
  )
}
