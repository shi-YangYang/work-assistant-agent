import type { DeliverableFile, DeliverableSummary } from '@paa/api-contracts'
import { useGeneratedFile } from '../../../hooks/deliverables/useGeneratedFile'
import styles from './AssistantReply.module.css'

function FileReference({
  item,
  file,
  label,
}: {
  item: DeliverableSummary
  file: DeliverableFile
  label: string
}) {
  const { download, busy, error } = useGeneratedFile(item.id, item.revision, file)
  return (
    <>
      <button
        type="button"
        className={styles['file-reference']}
        disabled={busy}
        onClick={() => void download()}
      >
        {label}
      </button>
      {error && <span role="alert">（{error instanceof Error ? error.message : error}）</span>}
    </>
  )
}

// Only current, server-authorized file metadata can turn a relative URL into
// an action. Downloads still use the common identity/permission-aware API path.
export function fileReference(items: DeliverableSummary[] = []) {
  const files = new Map(
    items.flatMap((item) =>
      (item.files ?? [])
        .filter(
          (file) =>
            Number.isSafeInteger(item.revision) &&
            item.revision > 0 &&
            file.url ===
              `/api/v1/deliverables/${encodeURIComponent(item.id)}/files/${encodeURIComponent(file.id)}?revision=${item.revision}`,
        )
        .map((file) => [file.url, { item, file }] as const),
    ),
  )
  return (href: string, label: string) => {
    const reference = files.get(href)
    return reference ? <FileReference {...reference} label={label} /> : undefined
  }
}
