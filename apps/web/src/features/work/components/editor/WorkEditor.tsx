import layoutStyles from '@web/styles/layout.module.css'
import controlsStyles from '@web/styles/controls.module.css'
import type { Work, WorkPatch } from '@paa/api-contracts'
import { ApiError } from '@web/api/client'
import { BusyButton } from '@web/components/actions/BusyButton'
import { ConflictRecovery } from '@web/components/forms/ConflictRecovery'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { Modal } from '@web/components/overlays/Modal'
import { FormField } from '@web/components/forms/FormField'
import { patchWork, readWork, progressFieldErrors } from '../../api/requests'
import { progressTitleError } from '../../utils/progress-edit'
import { useDraftSubmission } from '@web/hooks/useDraftSubmission'
import { useWorkspace } from '@web/lib/workspace'
import { useState } from 'react'
import { identityScope } from '@web/lib/session-drafts'
import { Status } from '@web/components/feedback/Status'
import { ChevronRight } from 'lucide-react'
import styles from './WorkEditor.module.css'

type Fields = Pick<Work, 'title' | 'status' | 'dueDate' | 'blocker' | 'nextStep'>
const fields = ({ title, status, dueDate, blocker, nextStep }: Work): Fields => ({
  title,
  status,
  dueDate,
  blocker,
  nextStep,
})
const changedFields = (value: Fields, base: Fields) =>
  Object.fromEntries(
    Object.entries(value).filter(([key, val]) => val !== base[key as keyof Fields]),
  ) as Partial<Fields>
export function WorkEditor({
  work,
  onClose,
  onSaved,
}: {
  work: Work
  onClose: () => void
  onSaved: () => void
}) {
  const { drafts, setDraft, identity } = useWorkspace()
  const key = `work:metadata:${work.id}`
  const scope = `${identityScope(identity)}:${work.id}`
  const createInitial = () => ({
    scope,
    content: fields(work),
    base: fields(work),
    revision: work.revision,
    key: crypto.randomUUID(),
  })
  const [initial, setInitial] = useState(createInitial)
  if (initial.scope !== scope) setInitial(createInitial())
  const stored = (drafts[key] as typeof initial | undefined) ?? initial
  const value = stored.content
  const { busy, submit } = useDraftSubmission(key)
  const [error, setError] = useState<Error | string>('')
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<keyof Fields, string>>>({})
  const change = (patch: Partial<Fields>) => {
    setFieldErrors({})
    setDraft(key, { ...stored, content: { ...value, ...patch }, key: crypto.randomUUID() })
  }
  return (
    <Modal
      title="编辑工作属性"
      onClose={onClose}
      className={styles.editor}
      bodyClassName={styles.body}
    >
      <form
        onSubmit={(event) => {
          event.preventDefault()
          const title = progressTitleError(value.title)
          setFieldErrors({ title })
          if (title) return
          setError('')
          const changed = changedFields(value, stored.base)
          if (!Object.keys(changed).length) {
            setDraft(key, undefined)
            onClose()
            return
          }
          void submit(
            () =>
              patchWork(
                work.id,
                { ...changed, expectedRevision: stored.revision } as WorkPatch,
                stored.key,
              ),
            () => {
              window.dispatchEvent(new Event('paa-record-updated'))
              onSaved()
            },
            (failure) => {
              setFieldErrors(progressFieldErrors(failure))
              setError(failure as Error)
            },
          )
        }}
      >
        <fieldset disabled={busy} className={styles.fields}>
          <FormField
            label="工作事项"
            value={value.title}
            required
            maxLength={200}
            error={fieldErrors.title}
            onChange={(event) => change({ title: event.target.value })}
          />
          <div className={styles.row}>
            <label className={styles.status}>
              状态
              <select
                value={value.status}
                onChange={(event) => change({ status: event.target.value as Work['status'] })}
              >
                <option value="in_progress">进行中</option>
                <option value="blocked">有阻碍</option>
                <option value="done">已完成</option>
              </select>
            </label>
            <FormField
              label="截止日期（选填）"
              type="date"
              max="9999-12-31"
              value={value.dueDate ?? ''}
              error={fieldErrors.dueDate}
              onChange={(event) => change({ dueDate: event.target.value || null })}
            />
          </div>
          <details className={styles.extra} open={!!(value.blocker || value.nextStep)}>
            <summary>
              <ChevronRight size={15} aria-hidden="true" />
              <span>阻碍与下一步</span>
              <small>选填</small>
            </summary>
            <div className={styles.extraFields}>
              <FormField
                label="问题或阻碍"
                value={value.blocker}
                maxLength={2000}
                error={fieldErrors.blocker}
                onChange={(event) => change({ blocker: event.target.value })}
              />
              <FormField
                label="下一步"
                value={value.nextStep}
                maxLength={2000}
                error={fieldErrors.nextStep}
                onChange={(event) => change({ nextStep: event.target.value })}
              />
            </div>
          </details>
        </fieldset>
        <ErrorNotice>{error}</ErrorNotice>
        {error instanceof ApiError && error.status === 409 && (
          <ConflictRecovery<Work>
            load={() => readWork(work)}
            render={(latest) => (
              <p>
                {latest.title} · 截止 {latest.dueDate || '未设置'} ·{' '}
                <Status value={latest.status} />
              </p>
            )}
            keep={(latest) => {
              setDraft(key, {
                ...stored,
                content: { ...fields(latest), ...changedFields(value, stored.base) },
                base: fields(latest),
                revision: latest.revision,
                key: crypto.randomUUID(),
              })
              setError('')
            }}
            replace={(latest) => {
              setDraft(key, {
                content: fields(latest),
                base: fields(latest),
                revision: latest.revision,
                key: crypto.randomUUID(),
              })
              setError('')
            }}
          />
        )}
        <div className={layoutStyles['form-actions']}>
          <button type="button" onClick={onClose}>
            稍后继续
          </button>
          <BusyButton busy={busy} className={controlsStyles.primary}>
            保存属性
          </BusyButton>
        </div>
      </form>
    </Modal>
  )
}
