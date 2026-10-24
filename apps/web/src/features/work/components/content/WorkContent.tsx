import type { Attachment, Work, WorkDocument } from '@paa/api-contracts'
import { useRef, useState, type ReactNode } from 'react'
import { Pencil } from 'lucide-react'
import { ApiError } from '@web/api/client'
import { BusyButton } from '@web/components/actions/BusyButton'
import { ConflictRecovery } from '@web/components/forms/ConflictRecovery'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { useWorkspace } from '@web/lib/workspace'
import { useDraftSubmission } from '@web/hooks/useDraftSubmission'
import { patchWork, readWork } from '../../api/requests'
import { useWorkUpload } from '../../hooks/useWorkUpload'
import {
  documentFromText,
  documentMaterialIds,
  removeDocumentMaterial,
  splitDocumentMaterials,
} from '../../utils/document'
import { WorkRichText } from './WorkRichText'
import { PendingMaterials } from '../materials/PendingMaterials'
import { ContentMaterial } from './ContentMaterial'
import controls from '@web/styles/controls.module.css'
import styles from './WorkContent.module.css'

type ContentDraft = { body: WorkDocument; files: Attachment[]; revision: number; key: string }
export function WorkContent({
  work: incoming,
  own,
  saved,
  renderHeader,
}: {
  work: Work
  own: boolean
  saved: () => void
  renderHeader?: (editAction: ReactNode) => ReactNode
}) {
  const [editing, setEditing] = useState(false)
  const [confirmed, setConfirmed] = useState<Work | null>(null)
  const work =
    confirmed?.id === incoming.id && confirmed.revision > incoming.revision && !incoming.historical
      ? confirmed
      : incoming
  const [checking, setChecking] = useState(false)
  const checkingRef = useRef(false)
  const [checkError, setCheckError] = useState<Error | string>('')
  const writable = own && !work.historical
  async function toggle(itemId: string, checked: boolean) {
    if (!writable || editing || checkingRef.current) return
    checkingRef.current = true
    setChecking(true)
    setCheckError('')
    try {
      const result = await patchWork(
        work.id,
        {
          expectedRevision: work.revision,
          bodyEdits: [{ action: 'set_checked', itemId, checked }],
        },
        crypto.randomUUID(),
      )
      setConfirmed(result.work)
      saved()
    } catch (error) {
      setCheckError(error instanceof Error ? error : '清单保存失败，请重试')
    } finally {
      checkingRef.current = false
      setChecking(false)
    }
  }
  const editAction = writable && !editing && (
    <button
      type="button"
      disabled={checking}
      className={`${controls.secondary} ${styles.editButton}`}
      onClick={() => setEditing(true)}
    >
      <Pencil size={15} aria-hidden="true" />
      编辑内容
    </button>
  )
  return (
    <>
      {renderHeader?.(editAction)}
      <section className={styles.section} aria-label="工作内容">
        {editing && writable ? (
          <ContentEditor
            work={work}
            close={() => setEditing(false)}
            saved={() => {
              setEditing(false)
              saved()
            }}
          />
        ) : work.body?.content.length || (!work.body && work.summary) ? (
          <WorkRichText
            body={work.body ?? documentFromText(work.summary)}
            work={work}
            own={own}
            toggle={writable ? toggle : undefined}
            disabled={checking}
          />
        ) : (
          <p className={styles.hint}>写下目标、方案或清单，也可以添加图片和文件。</p>
        )}
        {!renderHeader && editAction && <div className={styles.actions}>{editAction}</div>}
        {checking && (
          <small className={styles.saving} role="status">
            正在保存清单…
          </small>
        )}
        <ErrorNotice>{checkError}</ErrorNotice>
        {checkError instanceof ApiError && checkError.status === 409 && (
          <button
            type="button"
            className={controls['text-button']}
            onClick={() => {
              setCheckError('')
              saved()
            }}
          >
            读取当前内容
          </button>
        )}
      </section>
    </>
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
  const change = (
    patch: Partial<ContentDraft> | ((draft: ContentDraft) => Partial<ContentDraft>),
  ) =>
    setDraft(draftKey, (latest: unknown) => {
      const draft = (latest as ContentDraft | undefined) ?? value
      return {
        ...draft,
        ...(typeof patch === 'function' ? patch(draft) : patch),
        key: crypto.randomUUID(),
      }
    })
  const uploads = useWorkUpload(value.files, (files) =>
    change((draft) => {
      const ids = documentMaterialIds(draft.body)
      return {
        files,
        body: {
          ...draft.body,
          content: [
            ...draft.body.content,
            ...files
              .filter((file) => !ids.includes(file.id))
              .map((file) => ({
                type: 'material',
                attrs: { id: crypto.randomUUID(), materialId: file.id },
              })),
          ],
        },
      }
    }),
  )
  const editorBody = splitDocumentMaterials(value.body).body
  const existingIds = documentMaterialIds(value.body).filter(
    (id) => !value.files.some((file) => file.id === id),
  )
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
        body={editorBody}
        work={work}
        pending={value.files}
        change={(body) =>
          change((draft) => ({
            body: {
              ...body,
              content: [...body.content, ...splitDocumentMaterials(draft.body).materials],
            },
          }))
        }
        upload={uploads.upload}
        disabled={disabled}
      />
      {(existingIds.length > 0 || value.files.length > 0) && (
        <section className={styles.materials} aria-label="内容材料">
          <h4>材料</h4>
          {existingIds.map((id) => (
            <ContentMaterial
              key={id}
              id={id}
              work={work}
              disabled={disabled}
              remove={() => change((draft) => ({ body: removeDocumentMaterial(draft.body, id) }))}
            />
          ))}
          <PendingMaterials
            files={value.files}
            disabled={disabled}
            remove={(id) =>
              change((draft) => ({
                files: draft.files.filter((file) => file.id !== id),
                body: removeDocumentMaterial(draft.body, id),
              }))
            }
          />
        </section>
      )}
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
          {uploads.busy ? '上传中' : '保存内容'}
        </BusyButton>
      </div>
    </form>
  )
}
