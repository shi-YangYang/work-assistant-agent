import type { DeliverableReference, DeliverableSummary } from '@paa/api-contracts'
import { FileText, ArrowUpRight } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { DeliverablePanel } from './DeliverablePanel'
import styles from './Deliverable.module.css'

export function DeliverableEntry({
  item,
  onContinue,
}: {
  item: DeliverableSummary
  onContinue?: (reference: DeliverableReference, title: string, text?: string) => void
}) {
  const [open, setOpen] = useState(false)
  const continuation = useRef<Parameters<NonNullable<typeof onContinue>> | null>(null)
  useEffect(() => {
    if (open || !continuation.current) return
    const args = continuation.current
    continuation.current = null
    // Modal cleanup must release inert and restore its trigger before the
    // conversation updates and focuses the message input.
    onContinue?.(...args)
  }, [open, onContinue])
  return (
    <>
      <button className={styles.entry} onClick={() => setOpen(true)}>
        <FileText size={16} aria-hidden="true" />
        <span>查看{item.title}</span>
        <ArrowUpRight size={14} aria-hidden="true" />
      </button>
      {open && (
        <DeliverablePanel
          item={item}
          onClose={() => setOpen(false)}
          onContinue={
            onContinue
              ? (...args) => {
                  continuation.current = args
                }
              : undefined
          }
        />
      )}
    </>
  )
}
