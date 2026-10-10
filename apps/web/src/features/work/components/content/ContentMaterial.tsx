import type { Work, WorkMaterial } from '@paa/api-contracts'
import { useState } from 'react'
import { X } from 'lucide-react'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { Modal } from '@web/components/overlays/Modal'
import { useResource } from '@web/hooks/useResource'
import { fileSize } from '@web/utils/attachments'
import { MaterialView } from '../materials/MaterialView'
import styles from './WorkContent.module.css'

export function ContentMaterial({
  id,
  work,
  disabled,
  remove,
}: {
  id: string
  work: Work
  disabled: boolean
  remove: () => void
}) {
  const [preview, setPreview] = useState(false)
  const { data, error, refresh } = useResource<WorkMaterial>(
    `/work-items/${work.id}/materials/${id}`,
  )
  return (
    <div>
      <ErrorNotice retry={refresh}>{error}</ErrorNotice>
      {data ? (
        <div className={styles.material}>
          <button type="button" onClick={() => setPreview(true)}>
            {data.attachment.name}
          </button>
          <small>{fileSize(data.attachment.size)}</small>
          <button
            type="button"
            disabled={disabled}
            aria-label={`从内容移除 ${data.attachment.name}`}
            onClick={remove}
          >
            <X size={15} />
          </button>
        </div>
      ) : (
        !error && <small>正在读取材料…</small>
      )}
      {preview && data && (
        <Modal title={data.attachment.name} onClose={() => setPreview(false)}>
          <MaterialView attachment={data.attachment} refresh={refresh} />
        </Modal>
      )}
    </div>
  )
}
