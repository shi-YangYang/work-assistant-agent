import type { PersonaId } from '@paa/api-contracts'
import { Check, ChevronDown } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import styles from './PersonaPicker.module.css'

const personas: { id: PersonaId; name: string; description: string }[] = [
  {
    id: 'dabao',
    name: 'Noria人设',
    description: '亲切幽默，善于交流，认真办事。',
  },
  {
    id: 'professional',
    name: '专业人设',
    description: '冷静务实，结论清晰，建议具体。',
  },
]

export function PersonaPicker({
  value,
  disabled,
  onChange,
}: {
  value: PersonaId
  disabled: boolean
  onChange: (value: PersonaId) => void
}) {
  const [open, setOpen] = useState(false)
  const container = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const options = useRef<(HTMLButtonElement | null)[]>([])
  const id = useId()
  const expanded = open && !disabled
  useEffect(() => {
    if (!expanded) return
    options.current[personas.findIndex((persona) => persona.id === value)]?.focus()
    const outside = (event: PointerEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  }, [expanded, value])
  const close = () => {
    setOpen(false)
    trigger.current?.focus()
  }
  return (
    <div
      ref={container}
      className={styles.picker}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false)
      }}
    >
      <button
        ref={trigger}
        className={styles.trigger}
        aria-label={`选择人设：${personas.find((persona) => persona.id === value)?.name}`}
        aria-haspopup="menu"
        aria-expanded={expanded}
        aria-controls={expanded ? id : undefined}
        disabled={disabled}
        onClick={() => setOpen(!expanded)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault()
            setOpen(true)
          }
        }}
      >
        {personas.find((persona) => persona.id === value)?.name}
        <ChevronDown size={14} aria-hidden="true" />
      </button>
      {expanded && (
        <div
          id={id}
          role="menu"
          aria-label="助手人设"
          className={styles.menu}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.preventDefault()
              event.stopPropagation()
              close()
            }
            const index = options.current.indexOf(document.activeElement as HTMLButtonElement)
            const next =
              event.key === 'ArrowDown'
                ? (index + 1) % personas.length
                : event.key === 'ArrowUp'
                  ? (index + personas.length - 1) % personas.length
                  : event.key === 'Home'
                    ? 0
                    : event.key === 'End'
                      ? personas.length - 1
                      : null
            if (next !== null) {
              event.preventDefault()
              options.current[next]?.focus()
            }
          }}
        >
          {personas.map((persona, index) => (
            <button
              key={persona.id}
              ref={(element) => {
                options.current[index] = element
              }}
              role="menuitemradio"
              aria-checked={value === persona.id}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => {
                close()
                onChange(persona.id)
              }}
            >
              <span>
                {persona.name}
                <small>{persona.description}</small>
              </span>
              {value === persona.id && <Check size={16} aria-hidden="true" />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
