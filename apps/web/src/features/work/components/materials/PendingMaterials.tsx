import type { Attachment } from '@paa/api-contracts'
import { X } from 'lucide-react'
import styles from './WorkMaterials.module.css'

export function PendingMaterials({
  files,
  remove,
  disabled,
}: {
  files: Attachment[]
  remove: (id: string) => void
  disabled?: boolean
}) {
  if (!files.length) return null
  return (
    <>
      <div className={styles.pending}>
        {files.map((file) => (
          <div className={styles.chip} key={file.id}>
            <span title={file.name}>{file.name}</span>
            <button
              type="button"
              disabled={disabled}
              aria-label={`移除 ${file.name}`}
              onClick={() => remove(file.id)}
            >
              <X size={15} />
            </button>
          </div>
        ))}
      </div>
      <p className={styles.note}>保存后，材料随这项工作可见。</p>
    </>
  )
}
