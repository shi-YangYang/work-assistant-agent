import type { Attachment, Work, WorkUpdate, WorkUpdateInput } from '@paa/api-contracts'
import { useId, useRef, useState } from 'react'
import { ApiError } from '@web/api/client'
import { BusyButton } from '@web/components/actions/BusyButton'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { AutoTextarea } from '@web/components/forms/AutoTextarea'
import { ConflictRecovery } from '@web/components/forms/ConflictRecovery'
import { FormField } from '@web/components/forms/FormField'
import { useDraftSubmission } from '@web/hooks/useDraftSubmission'
import { useWorkspace } from '@web/lib/workspace'
import { fileAccept } from '@web/utils/attachments'
import { Paperclip, X } from 'lucide-react'
import { readUpdateVersion, saveWorkUpdate } from '../../api/requests'
import { useWorkUpload } from '../../hooks/useWorkUpload'
import { PendingMaterials } from '../materials/PendingMaterials'
import { WorkMaterialDisplay } from '../content/MaterialNode'
import styles from './WorkUpdates.module.css'
import controls from '@web/styles/controls.module.css'

type UpdateDraft = {
  text: string
  files: Attachment[]
  materialIds: string[]
  revision: number
  updateRevision?: number
  key: string
  properties: Partial<Pick<WorkUpdateInput, 'status' | 'dueDate' | 'blocker' | 'nextStep'>>
}
export function UpdateEditor({
  work,
  entry,
  close,
  saved,
}: {
  work: Work
  entry?: WorkUpdate
  close: () => void
  saved: () => void
}) {
  const { drafts, setDraft } = useWorkspace()
  const draftKey = `work:update:${work.id}:${entry?.id ?? 'new'}`
  const [initial] = useState<UpdateDraft>(() => ({
    text: entry?.text ?? '',
    files: [],
    materialIds: entry?.materialIds ?? [],
    revision: work.revision,
    updateRevision: entry?.revision,
    key: crypto.randomUUID(),
    properties: {},
  }))
  const value = (drafts[draftKey] as UpdateDraft | undefined) ?? initial
  const { busy, submit } = useDraftSubmission(draftKey)
  const [error, setError] = useState<Error | string>('')
  const picker = useRef<HTMLInputElement>(null)
  const textId = useId()
  const change = (patch: Partial<UpdateDraft>) =>
    setDraft(draftKey, (latest: unknown) => ({
      ...((latest as typeof value | undefined) ?? value),
      ...patch,
      key: crypto.randomUUID(),
    }))
  const uploads = useWorkUpload(value.files, (files) => change({ files }))
  const disabled = busy || uploads.busy
  return (
    <form
      className={styles.editor}
      onSubmit={(event) => {
        event.preventDefault()
        if (disabled) return
        if (!value.text.trim() && !value.files.length && !value.materialIds.length) {
          setError('请填写进展或添加材料')
          return
        }
        if (value.materialIds.length + value.files.length > 9) {
          setError('每条进展最多添加 9 个附件')
          return
        }
        setError('')
        void submit(
          () =>
            saveWorkUpdate(
              work.id,
              {
                text: value.text,
                materialIds: value.materialIds,
                materials: value.files.map((file) => ({ attachmentId: file.id })),
                expectedRevision: value.revision,
                ...(entry ? { expectedUpdateRevision: value.updateRevision } : {}),
                ...value.properties,
              },
              value.key,
              entry?.id,
            ),
          () => {
            window.dispatchEvent(new Event('paa-record-updated'))
            saved()
          },
          (failure) => setError(failure as Error),
        )
      }}
    >
      <div>
        <label htmlFor={textId}>{entry ? '更正进展' : '记录新进展'}</label>
        <AutoTextarea
          id={textId}
          disabled={disabled}
          value={value.text}
          maxLength={12000}
          rows={3}
          placeholder="发生了什么变化？可以只写一句，也可以附上材料。"
          onChange={(event) => change({ text: event.target.value })}
        />
      </div>
      {value.materialIds.map((id) => (
        <div className={styles.existing} key={id}>
          <WorkMaterialDisplay id={id} work={work} />
          <button
            type="button"
            disabled={disabled}
            aria-label="移除此进展材料"
            onClick={() => change({ materialIds: value.materialIds.filter((item) => item !== id) })}
          >
            <X size={16} />
          </button>
        </div>
      ))}
      <PendingMaterials
        files={value.files}
        disabled={disabled}
        remove={(id) => change({ files: value.files.filter((file) => file.id !== id) })}
      />
      <details className={styles.properties}>
        <summary>同时调整状态或下一步（选填）</summary>
        <fieldset disabled={disabled}>
          <label>
            状态
            <select
              value={value.properties.status ?? ''}
              onChange={(event) =>
                change({
                  properties: {
                    ...value.properties,
                    status: (event.target.value as Work['status']) || undefined,
                  },
                })
              }
            >
              <option value="">保持不变</option>
              <option value="in_progress">进行中</option>
              <option value="blocked">有阻碍</option>
              <option value="done">整个事项已完成</option>
            </select>
          </label>
          <FormField
            label="截止日期"
            type="date"
            value={
              value.properties.dueDate === undefined
                ? (work.dueDate ?? '')
                : (value.properties.dueDate ?? '')
            }
            onChange={(event) =>
              change({ properties: { ...value.properties, dueDate: event.target.value || null } })
            }
          />
          <FormField
            label="问题或阻碍"
            value={value.properties.blocker ?? work.blocker}
            maxLength={2000}
            onChange={(event) =>
              change({ properties: { ...value.properties, blocker: event.target.value } })
            }
          />
          <FormField
            label="下一步"
            value={value.properties.nextStep ?? work.nextStep}
            maxLength={2000}
            onChange={(event) =>
              change({ properties: { ...value.properties, nextStep: event.target.value } })
            }
          />
        </fieldset>
      </details>
      <ErrorNotice>{error || uploads.error}</ErrorNotice>
      {error instanceof ApiError && error.status === 409 && (
        <ConflictRecovery<Awaited<ReturnType<typeof readUpdateVersion>>>
          load={() => readUpdateVersion(work, entry?.id)}
          render={(latest) => (
            <>
              <p>
                {latest.work.title} · 第 {latest.work.revision} 版
              </p>
              <p>{latest.update?.text || '附件进展'}</p>
            </>
          )}
          keep={(latest) => {
            change({ revision: latest.work.revision, updateRevision: latest.update?.revision })
            setError('')
          }}
          replace={(latest) => {
            change({
              revision: latest.work.revision,
              updateRevision: latest.update?.revision,
              ...(latest.update
                ? {
                    text: latest.update.text,
                    materialIds: latest.update.materialIds,
                    files: [],
                    properties: {},
                  }
                : {}),
            })
            setError('')
          }}
        />
      )}
      <div className={styles.actions}>
        <input
          ref={picker}
          hidden
          type="file"
          multiple
          accept={fileAccept}
          aria-label="进展材料"
          onChange={(event) => {
            void uploads.upload(Array.from(event.target.files ?? []))
            event.target.value = ''
          }}
        />
        <button type="button" disabled={disabled} onClick={() => picker.current?.click()}>
          <Paperclip size={16} />
          添加材料
        </button>
        <span />
        <button type="button" disabled={disabled} onClick={close}>
          稍后继续
        </button>
        <BusyButton busy={disabled} className={controls.primary}>
          {uploads.busy ? '上传中' : entry ? '保存更正' : '保存进展'}
        </BusyButton>
      </div>
    </form>
  )
}
