import type { DeliverableReference, DeliverableSummary } from '@paa/api-contracts'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Markdown } from '@web/components/Markdown'
import { Modal } from '@web/components/Modal'
import { Check, Copy, MessageSquare, ChevronLeft, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { useDeliverable } from '../hooks/useDeliverable'
import controls from '@web/styles/controls.module.css'
import styles from './Deliverable.module.css'

export function DeliverablePanel({
  item,
  onClose,
  onContinue,
}: {
  item: DeliverableSummary
  onClose: () => void
  onContinue?: (reference: DeliverableReference, title: string, text?: string) => void
}) {
  const { data, error, refresh, revision, setRevision } = useDeliverable(item)
  const [selected, setSelected] = useState<string[]>([])
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState('')
  const current = data?.revision === revision ? data : null
  const continueChat = (add = false) => {
    if (!current || !onContinue) return
    const numbers = current.items
      .map((entry, index) => (selected.includes(entry.id) ? index + 1 : null))
      .filter((number) => number !== null)
    onContinue(
      { id: current.id, revision: current.revision, itemIds: selected },
      current.title,
      add ? `把《${current.title}》第 ${numbers.join('、')} 项加入我的工作。` : undefined,
    )
    onClose()
  }
  return (
    <Modal title={current?.title ?? item.title} variant="drawer" onClose={onClose}>
      <ErrorNotice retry={refresh}>{error}</ErrorNotice>
      {!current && !error && <p role="status">正在读取内容…</p>}
      {current && (
        <div className={styles.reader}>
          <div className={styles.toolbar}>
            <details className={styles.versions}>
              <summary>版本 {current.revision}</summary>
              <div>
                <button
                  aria-label="上一版本"
                  disabled={revision === 1}
                  onClick={() => {
                    setSelected([])
                    setRevision(revision - 1)
                  }}
                >
                  <ChevronLeft size={16} />
                </button>
                <span>
                  {revision} / {current.latestRevision}
                </span>
                <button
                  aria-label="下一版本"
                  disabled={revision >= current.latestRevision}
                  onClick={() => {
                    setSelected([])
                    setRevision(revision + 1)
                  }}
                >
                  <ChevronRight size={16} />
                </button>
              </div>
            </details>
            <button
              className={controls['text-button']}
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(
                    [
                      current.title,
                      current.body,
                      ...current.items.map(
                        (entry, index) => `${index + 1}. ${entry.title}\n${entry.body}`,
                      ),
                    ]
                      .filter(Boolean)
                      .join('\n\n'),
                  )
                  setCopied(true)
                  setCopyError('')
                } catch {
                  setCopyError('复制失败，请选中文字复制')
                }
              }}
            >
              {copied ? <Check size={15} /> : <Copy size={15} />}
              {copied ? '已复制' : '复制'}
            </button>
          </div>
          <ErrorNotice>{copyError}</ErrorNotice>
          {current.body && <Markdown text={current.body} />}
          {current.items.length > 0 && (
            <ol className={styles.items}>
              {current.items.map((entry) => (
                <li key={entry.id}>
                  <h3>{entry.title}</h3>
                  <Markdown text={entry.body} />
                </li>
              ))}
            </ol>
          )}
          {onContinue && (
            <div className={styles.actions}>
              <button className={controls.primary} onClick={() => continueChat()}>
                <MessageSquare size={16} />
                继续修改
              </button>
              {current.items.length > 0 && (
                <details className={styles.selection}>
                  <summary>选择条目加入工作</summary>
                  <div>
                    {current.items.map((entry, index) => (
                      <label key={entry.id}>
                        <input
                          type="checkbox"
                          checked={selected.includes(entry.id)}
                          onChange={(event) =>
                            setSelected(
                              event.target.checked
                                ? [...selected, entry.id]
                                : selected.filter((id) => id !== entry.id),
                            )
                          }
                        />
                        <span>
                          {index + 1}. {entry.title}
                        </span>
                      </label>
                    ))}
                    <button disabled={!selected.length} onClick={() => continueChat(true)}>
                      加入我的工作
                    </button>
                  </div>
                </details>
              )}
            </div>
          )}
        </div>
      )}
    </Modal>
  )
}
