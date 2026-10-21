import type {
  DeliverableReference,
  DeliverableSummary,
  ImageGenerationSlot,
  Job,
} from '@paa/api-contracts'
import { Modal } from '@web/components/overlays/Modal'
import { FileText, ArrowUpRight } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { DeliverablePanel } from './DeliverablePanel'
import { GeneratedFiles, GeneratedImages } from './GeneratedFiles'
import styles from './Deliverable.module.css'
import cardStyles from '@web/styles/patterns/ResourceCard.module.css'

export function MessageDeliverables({
  items,
  complete,
  generation,
  state,
  onContinue,
}: {
  items: DeliverableSummary[]
  complete: boolean
  generation?: ImageGenerationSlot[]
  state?: Job['state']
  onContinue?: (reference: DeliverableReference, title: string, text?: string) => void
}) {
  const imageResults = items.filter(
    (item) => item.files?.length && item.files.every((file) => file.mimeType === 'image/png'),
  )
  const grouped = imageResults.length > 1
  return (
    <>
      <GeneratedImages items={items} generation={generation} state={state} />
      {complete && grouped && <ImageTaskEntry items={imageResults} />}
      {items
        .filter((item) => !grouped || !imageResults.includes(item))
        .map((item) => (
          <DeliverableEntry
            key={`${item.id}:${item.revision}`}
            item={item}
            onContinue={onContinue}
            includeImages={false}
            showEntry={complete || !item.files?.some((file) => file.mimeType === 'image/png')}
          />
        ))}
    </>
  )
}

function ImageTaskEntry({ items }: { items: DeliverableSummary[] }) {
  const [open, setOpen] = useState(false)
  const title = items.every((item) => item.title === items[0].title)
    ? items[0].title
    : `生成图片（${items.reduce((count, item) => count + (item.files?.length ?? 0), 0)}张）`
  return (
    <>
      <button
        className={`${cardStyles.card} ${cardStyles.row} ${styles.entry}`}
        aria-label={`查看${title}`}
        onClick={() => setOpen(true)}
      >
        <span className={cardStyles.icon} aria-hidden="true">
          <FileText size={24} />
        </span>
        <span className={cardStyles.content}>
          <span className={`${cardStyles.title} ${styles.entryTitle}`}>{title}</span>
          <span className={cardStyles.meta}>查看详情</span>
        </span>
        <ArrowUpRight className={styles.entryArrow} size={16} aria-hidden="true" />
      </button>
      {open && (
        <Modal title={title} variant="drawer" onClose={() => setOpen(false)}>
          <GeneratedImages items={items} />
        </Modal>
      )}
    </>
  )
}

export function DeliverableEntry({
  item,
  onContinue,
  includeImages = true,
  showEntry = true,
}: {
  item: DeliverableSummary
  onContinue?: (reference: DeliverableReference, title: string, text?: string) => void
  includeImages?: boolean
  showEntry?: boolean
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
      {includeImages && (
        <GeneratedFiles
          deliverableId={item.id}
          revision={item.revision}
          files={item.files?.filter((file) => file.mimeType === 'image/png')}
        />
      )}
      {showEntry && (
        <button
          className={`${cardStyles.card} ${cardStyles.row} ${styles.entry}`}
          aria-label={`查看${item.title}`}
          onClick={() => setOpen(true)}
        >
          <span className={cardStyles.icon} aria-hidden="true">
            <FileText size={24} />
          </span>
          <span className={cardStyles.content}>
            <span className={`${cardStyles.title} ${styles.entryTitle}`}>{item.title}</span>
            <span className={cardStyles.meta}>查看详情</span>
          </span>
          <ArrowUpRight className={styles.entryArrow} size={16} aria-hidden="true" />
        </button>
      )}
      {showEntry && open && (
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
