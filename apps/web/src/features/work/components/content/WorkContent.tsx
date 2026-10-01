import type { Attachment, Work, WorkDocument } from '@paa/api-contracts'
import { useState } from 'react'
import { ApiError } from '@web/api/client'
import { BusyButton } from '@web/components/actions/BusyButton'
import { ConflictRecovery } from '@web/components/forms/ConflictRecovery'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { useWorkspace } from '@web/lib/workspace'
import { useDraftSubmission } from '@web/hooks/useDraftSubmission'
import { patchWork, readWork } from '../../api/requests'
import { useWorkUpload } from '../../hooks/useWorkUpload'
import { documentFromText, documentMaterialIds, removeDocumentMaterial } from '../../utils/document'
import { WorkRichText } from './WorkRichText'
import { PendingMaterials } from '../materials/PendingMaterials'
import controls from '@web/styles/controls.module.css'
import styles from './WorkContent.module.css'

type ContentDraft = { body: WorkDocument; files: Attachment[]; revision: number; key: string }
export function WorkContent({ work, own, saved }: { work: Work; own: boolean; saved: () => void }) {
  const [editing, setEditing] = useState(false)
  return (
    <section className={styles.section} aria-label="工作内容">
      <div className={styles.heading}>
        <h3>工作内容</h3>
        {own && !editing && <button onClick={() => setEditing(true)}>编辑正文</button>}
      </div>
      {editing && own ? (
        <ContentEditor
          work={work}
          close={() => setEditing(false)}
          saved={() => {
            setEditing(false)
            saved()
          }}
        />
      ) : work.body?.content.length || (!work.body && work.summary) ? (
        <WorkRichText body={work.body ?? documentFromText(work.summary)} work={work} own={own} />
      ) : (
        <p className={styles.hint}>写下目标、方案或清单，也可以添加图片和文件。</p>
      )}
    </section>
  )
}
function ContentEditor({
  work,
  close,
  saved,
}: {
  work: Work
  close: () => void
  saved: () => void
}) {
  const { drafts, setDraft } = useWorkspace()
  const draftKey = `work:body:${work.id}`
  const [initial] = useState<ContentDraft>(() => ({
    body: work.body ?? documentFromText(work.summary),
    files: [],
    revision: work.revision,
    key: crypto.randomUUID(),
  }))
  const value = (drafts[draftKey] as ContentDraft | undefined) ?? initial
  const { busy, submit } = useDraftSubmission(draftKey)
  const [error, setError] = useState<Error | string>('')
  const change = (patch: Partial<ContentDraft>) =>
    setDraft(draftKey, (latest: unknown) => ({
      ...((latest as typeof value | undefined) ?? value),
      ...patch,
      key: crypto.randomUUID(),
    }))
  const uploads = useWorkUpload(value.files, (files) => change({ files }))
  const disabled = busy || uploads.busy
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        if (disabled) return
        setError('')
        const ids = documentMaterialIds(value.body)
        void submit(
          () =>
            patchWork(
              work.id,
              {
                body: value.body,
                expectedRevision: value.revision,
                materials: value.files
                  .filter((file) => ids.includes(file.id))
                  .map((file) => ({ attachmentId: file.id })),
              },
              value.key,
            ),
          saved,
          (failure) => setError(failure as Error),
        )
      }}
    >
      <WorkRichText
        body={value.body}
        work={work}
        pending={value.files}
        change={(body) => change({ body })}
        upload={uploads.upload}
        disabled={disabled}
      />
      <PendingMaterials
        files={value.files}
        disabled={disabled}
        remove={(id) =>
          change({
            files: value.files.filter((file) => file.id !== id),
            body: removeDocumentMaterial(value.body, id),
          })
        }
      />
      <ErrorNotice>{error || uploads.error}</ErrorNotice>
      {error instanceof ApiError && error.status === 409 && (
        <ConflictRecovery<Work>
          load={() => readWork(work)}
          render={(latest) => (
            <WorkRichText body={latest.body ?? documentFromText(latest.summary)} work={latest} />
          )}
          keep={(latest) => {
            change({ revision: latest.revision })
            setError('')
          }}
          replace={(latest) => {
            change({
              body: latest.body ?? documentFromText(latest.summary),
              files: [],
              revision: latest.revision,
            })
            setError('')
          }}
        />
      )}
      <div className={styles.actions}>
        <button
          type="button"
          disabled={disabled}
          onClick={() => {
            setDraft(draftKey, undefined)
            close()
          }}
        >
          取消
        </button>
        <BusyButton busy={disabled} className={controls.primary}>
          {uploads.busy ? '上传中' : '保存正文'}
        </BusyButton>
      </div>
    </form>
  )
}
