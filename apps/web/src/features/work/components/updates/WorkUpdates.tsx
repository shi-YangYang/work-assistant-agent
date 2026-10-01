import type { Work, WorkPageResult, WorkUpdate } from '@paa/api-contracts'
import { useState } from 'react'
import { useResource } from '@web/hooks/useResource'
import { Modal } from '@web/components/overlays/Modal'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { BusyButton } from '@web/components/actions/BusyButton'
import { Actions } from '@web/components/actions/Actions'
import { dateLabel } from '@web/utils/date'
import { deleteWorkUpdate, workRecordsPath } from '../../api/requests'
import { WorkMaterialDisplay } from '../content/MaterialNode'
import { UpdateEditor } from './UpdateEditor'
import styles from './WorkUpdates.module.css'
import controls from '@web/styles/controls.module.css'

export function WorkUpdates({ work, own, saved }: { work: Work; own: boolean; saved: () => void }) {
  const [adding, setAdding] = useState(false)
  return (
    <section className={styles.section} aria-label="工作进展">
      <div className={styles.heading}>
        <h3>进展</h3>
        {own && !adding && <button onClick={() => setAdding(true)}>记录新进展</button>}
      </div>
      {adding && own && (
        <UpdateEditor
          work={work}
          close={() => setAdding(false)}
          saved={() => {
            setAdding(false)
            saved()
          }}
        />
      )}
      <UpdateList key={`${work.id}:${work.revision}`} work={work} own={own} saved={saved} />
    </section>
  )
}
function UpdateList({ work, own, saved }: { work: Work; own: boolean; saved: () => void }) {
  const [starts, setStarts] = useState([0])
  const { data, error, refresh } = useResource<WorkPageResult<WorkUpdate>>(
    workRecordsPath(work, 'updates', starts.at(-1)),
  )
  const [editing, setEditing] = useState<WorkUpdate | null>(null)
  const [deleting, setDeleting] = useState<WorkUpdate | null>(null)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<Error | string>('')
  const [key, setKey] = useState(() => crypto.randomUUID())
  return (
    <>
      <ErrorNotice retry={refresh}>{error}</ErrorNotice>
      {data?.items.map((entry) => (
        <article className={styles.entry} key={entry.id}>
          <div className={styles.meta}>
            <span>
              {entry.origin.startsWith('assistant')
                ? '助手记录'
                : entry.origin === 'legacy'
                  ? '历史记录'
                  : '手动记录'}{' '}
              · {dateLabel(entry.createdAt)}
              {entry.revision > 1 ? ' · 已更正' : ''}
            </span>
            {own && (
              <Actions label="管理进展">
                <button role="menuitem" onClick={() => setEditing(entry)}>
                  更正进展
                </button>
                <button
                  role="menuitem"
                  className={controls.danger}
                  onClick={() => {
                    setFailure('')
                    setKey(crypto.randomUUID())
                    setDeleting(entry)
                  }}
                >
                  删除进展
                </button>
              </Actions>
            )}
          </div>
          <p className={styles.text}>{entry.text}</p>
          <div className={styles.materials}>
            {entry.materialIds.map((id) => (
              <WorkMaterialDisplay key={id} id={id} work={work} own={own} />
            ))}
          </div>
        </article>
      ))}
      {data && !data.items.length && (
        <p className={styles.empty}>还没有进展记录。工作内容中的计划会保留在正文里。</p>
      )}
      {data && (starts.length > 1 || data.nextCursor !== null) && (
        <div className={styles.pages}>
          <button disabled={starts.length < 2} onClick={() => setStarts(starts.slice(0, -1))}>
            上一页
          </button>
          <span>第 {starts.length} 页</span>
          <button
            disabled={data.nextCursor === null}
            onClick={() => setStarts([...starts, data.nextCursor!])}
          >
            下一页
          </button>
        </div>
      )}
      {editing && own && (
        <Modal title="更正进展" onClose={() => setEditing(null)}>
          <UpdateEditor
            work={work}
            entry={editing}
            close={() => setEditing(null)}
            saved={() => {
              setEditing(null)
              saved()
            }}
          />
        </Modal>
      )}
      {deleting && own && (
        <Modal title="删除进展" onClose={() => !busy && setDeleting(null)}>
          <p>删除这条进展？工作正文及其他进展会保留。</p>
          <p className={styles.text}>{deleting.text || '附件进展'}</p>
          <ErrorNotice>{failure}</ErrorNotice>
          <div className={styles.actions}>
            <button disabled={busy} onClick={() => setDeleting(null)}>
              取消
            </button>
            <BusyButton
              busy={busy}
              className={controls.danger}
              onClick={async () => {
                setBusy(true)
                try {
                  await deleteWorkUpdate(work, deleting.id, deleting.revision, key)
                  setDeleting(null)
                  saved()
                } catch (error) {
                  setFailure(error as Error)
                } finally {
                  setBusy(false)
                }
              }}
            >
              删除进展
            </BusyButton>
          </div>
        </Modal>
      )}
    </>
  )
}
