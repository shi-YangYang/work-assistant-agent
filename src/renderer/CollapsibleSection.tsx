import { useId, useState, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'

export function CollapsibleSection({
  id,
  title,
  summary,
  error = false,
  className = '',
  children,
}: {
  id: string
  title: string
  summary: string
  error?: boolean
  className?: string
  children: ReactNode
}): React.JSX.Element {
  const contentId = useId()
  const [expanded, setExpanded] = useState(() => {
    try {
      return localStorage.getItem(`paa.settings.expanded.${id}`) === 'true'
    } catch {
      return false
    }
  })
  return (
    <section className={`settings-card collapsible-section ${className}`} aria-label={title}>
      <h2>
        <button
          className="section-toggle"
          aria-expanded={expanded}
          aria-controls={contentId}
          onClick={() => {
            const next = !expanded
            setExpanded(next)
            try {
              localStorage.setItem(`paa.settings.expanded.${id}`, String(next))
            } catch {
              /* Preferences are optional when browser storage is unavailable. */
            }
          }}
        >
          <span>{title}</span>
          <ChevronDown size={19} className={expanded ? 'expanded' : ''} />
        </button>
      </h2>
      <p
        className={`section-summary ${error ? 'audio-warning' : ''}`}
        role={error && !expanded ? 'alert' : 'status'}
      >
        {summary}
      </p>
      <div id={contentId} hidden={!expanded} className="collapsible-content">
        {children}
      </div>
    </section>
  )
}
