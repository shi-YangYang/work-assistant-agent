import { ChevronDown } from 'lucide-react'
import type { ReactNode } from 'react'
import { useId } from 'react'

export function PanelSection({
  title,
  status,
  defaultOpen = false,
  children,
}: {
  title: string
  status?: ReactNode
  defaultOpen?: boolean
  children: ReactNode
}) {
  const id = useId()
  return (
    <details
      className="panel-section"
      open={defaultOpen}
      onInvalidCapture={(event) => {
        // Reveal invalid fields before native form validation tries to focus them.
        event.currentTarget.open = true
      }}
    >
      <summary>
        <h3 id={id}>{title}</h3>
        {status && <span className="panel-section-status">{status}</span>}
        <ChevronDown size={18} className="panel-section-chevron" aria-hidden="true" />
      </summary>
      <div className="panel-section-body" role="region" aria-labelledby={id}>
        {children}
      </div>
    </details>
  )
}
