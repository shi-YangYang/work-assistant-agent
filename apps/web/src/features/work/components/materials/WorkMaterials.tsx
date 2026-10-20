import type { Work, WorkMaterial, WorkPageResult } from '@paa/api-contracts'
import { useState } from 'react'
import { useResource } from '@web/hooks/useResource'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { Modal } from '@web/components/overlays/Modal'
import { BusyButton } from '@web/components/actions/BusyButton'
import { fileSize } from '@web/utils/attachments'
import { removeWorkMaterial, workRecordsPath } from '../../api/requests'
import { documentMaterialIds } from '../../utils/document'
import { MaterialView } from './MaterialView'
import styles from './WorkMaterials.module.css'
import controls from '@web/styles/controls.module.css'

export function WorkMaterials({
  work,
  own,
  saved,
}: {
  work: Work
  own: boolean
  saved: () => void
}) {
  if (!work.materialIds?.length) return <p>暂无附件</p>
  return <MaterialList key={`${work.id}:${work.revision}`} work={work} own={own} saved={saved} />
}
function MaterialList({ work, own, saved }: { work: Work; own: boolean; saved: () => void }) {
  const [starts, setStarts] = useState([0])
  const { data, error, refresh } = useResource<WorkPageResult<WorkMaterial>>(
    workRecordsPath(work, 'materials', starts.at(-1)),
  )
  const [selected, setSelected] = useState<WorkMaterial | null>(null)
  const [removing, setRemoving] = useState<WorkMaterial | null>(null)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<Error | string>('')
  const [key, setKey] = useState(() => crypto.randomUUID())
  const bodyIds = documentMaterialIds(work.body)
  return (
    <>
      <ErrorNotice retry={refresh}>{error}</ErrorNotice>
      <div className={styles.list}>
        {data?.items.map((material) => (
          <div key={material.id} className={styles.row}>
            <div className={styles.caption}>
              <button className={styles.filename} onClick={() => setSelected(material)}>
                {material.attachment.name}
              </button>
              <small>{fileSize(material.attachment.size)}</small>
              {own && !bodyIds.includes(material.id) && (
                <button
                  className={controls['text-button']}
                  onClick={() => {
                    setFailure('')
                    setKey(crypto.randomUUID())
                    setRemoving(material)
                  }}
                >
                  移除材料
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
      {data && (starts.length > 1 || data.nextCursor !== null) && (
        <div className={styles.caption}>
          <button disabled={starts.length < 2} onClick={() => setStarts(starts.slice(0, -1))}>
            上一组材料
          </button>
          <button
            disabled={data.nextCursor === null}
            onClick={() => setStarts([...starts, data.nextCursor!])}
          >
            下一组材料
          </button>
        </div>
      )}
      {selected && (
        <Modal title={selected.attachment.name} onClose={() => setSelected(null)}>
          <MaterialView attachment={selected.attachment} own={own} refresh={refresh} />
        </Modal>
      )}
      {removing && own && (
        <Modal title="移除材料" onClose={() => !busy && setRemoving(null)}>
          <p>从当前工作移除 {removing.attachment.name}？仍被进展引用的材料需要先从对应条目移除。</p>
          <ErrorNotice>{failure}</ErrorNotice>
          <div className={styles.caption}>
            <button disabled={busy} onClick={() => setRemoving(null)}>
              取消
            </button>
            <BusyButton
              busy={busy}
              className={controls.danger}
              onClick={async () => {
                setBusy(true)
                try {
                  await removeWorkMaterial(work, removing, key)
                  setRemoving(null)
                  saved()
                } catch (error) {
                  setFailure(error as Error)
                } finally {
                  setBusy(false)
                }
              }}
            >
              确认移除
            </BusyButton>
          </div>
        </Modal>
      )}
    </>
  )
}
