import layoutStyles from '../../../styles/layout.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import type { Draft, Page, Progress, Work } from '@paa/api-contracts'
import { ApiError } from '@web/api/client'
import { BusyButton } from '@web/components/BusyButton'
import { ConflictRecovery } from '@web/components/ConflictRecovery'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Modal } from '@web/components/Modal'
import {
  availableWorkPath,
  readProgressSource,
  updateProgressDraft,
} from '@web/features/work/api/requests'
import { ProgressFields } from '@web/features/work/components/ProgressFields'
import type { ProgressEdit } from '@web/features/work/utils/progress-edit'
import {
  progressEditValue,
  progressFieldErrors,
  progressTitleError,
} from '@web/features/work/utils/progress-edit'
import { useResource } from '@web/hooks/useResource'
import { useWorkspace } from '@web/lib/workspace'
import { useState } from 'react'

export function ProgressEditor({
  draft,
  onClose,
  onSaved,
}: {
  draft: Draft
  onClose: () => void
  onSaved: () => void
}) {
  const { drafts, setDraft } = useWorkspace()
  const key = `progress:${draft.id}`
  const stored = drafts[key] as ProgressEdit | undefined
  const edited = progressEditValue(draft, stored)
  const { content: value, workId, revision } = edited
  const { data } = useResource<Page<Work>>(availableWorkPath())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<keyof Progress, string>>>({})
  const change = (content: Progress, nextWork = workId) => {
    setFieldErrors({})
    setDraft(key, { content, workId: nextWork, revision })
  }
  return (
    <Modal title="编辑进展建议" onClose={onClose}>
      <form
        onSubmit={async (e) => {
          e.preventDefault()
          const title = progressTitleError(value.title)
          setFieldErrors({ title })
          if (title) return
          setError('')
          setBusy(true)
          try {
            await updateProgressDraft(draft, { ...value, workId, expectedRevision: revision })
            setDraft(key, undefined)
            onSaved()
          } catch (e) {
            setFieldErrors(progressFieldErrors(e))
            setError(e as Error)
          } finally {
            setBusy(false)
          }
        }}
      >
        <label>
          关联工作
          <select value={workId ?? ''} onChange={(e) => change(value, e.target.value || null)}>
            <option value="">新建工作事项</option>
            {data?.items.map((w) => (
              <option key={w.id} value={w.id}>
                {w.title}
              </option>
            ))}
          </select>
        </label>
        <ProgressFields value={value} change={change} errors={fieldErrors} />
        <ErrorNotice>{error}</ErrorNotice>
        {error instanceof ApiError && error.status === 409 && (
          <ConflictRecovery<Draft>
            load={async () => {
              const message = await readProgressSource(draft)
              const latest = message.drafts.find((d) => d.id === draft.id)
              if (!latest) throw new Error('这条建议已不再可用')
              return latest
            }}
            render={(latest) => (
              <>
                <p>
                  {latest.content.title}：{latest.content.summary}
                </p>
                <p>{latest.content.blocker}</p>
                <p>{latest.content.nextStep}</p>
              </>
            )}
            keep={(latest) => {
              setDraft(key, { ...edited, revision: latest.revision })
              setError('')
            }}
            replace={(latest) => {
              setDraft(key, {
                content: latest.content,
                workId: latest.workId,
                revision: latest.revision,
              })
              setError('')
            }}
          />
        )}
        <div className={layoutStyles['form-actions']}>
          <button type="button" onClick={onClose}>
            稍后继续
          </button>
          <BusyButton busy={busy} className={controlsStyles['primary']}>
            保存修改
          </BusyButton>
        </div>
      </form>
    </Modal>
  )
}
