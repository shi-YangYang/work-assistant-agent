import type { Work } from '@paa/api-contracts'
import { useState } from 'react'
import { BusyButton } from '@web/components/actions/BusyButton'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { FormField } from '@web/components/forms/FormField'
import { Modal } from '@web/components/overlays/Modal'
import { useDraftSubmission } from '@web/hooks/useDraftSubmission'
import { useWorkspace } from '@web/lib/workspace'
import { createWork, progressFieldErrors } from '../../api/requests'
import { progressTitleError } from '../../utils/progress-edit'
import { documentFromText } from '../../utils/document'
import layout from '@web/styles/layout.module.css'
import controls from '@web/styles/controls.module.css'

export function CreateWork({
  onClose,
  onSaved,
}: {
  onClose: () => void
  onSaved: (work: Work) => void
}) {
  const { drafts, setDraft } = useWorkspace()
  const [initial] = useState(() => ({
    title: '',
    description: '',
    dueDate: '',
    key: crypto.randomUUID(),
  }))
  const value = (drafts['work:new'] as typeof initial | undefined) ?? initial
  const { busy, submit } = useDraftSubmission('work:new')
  const [error, setError] = useState<Error | string>('')
  const [titleError, setTitleError] = useState('')
  const [dateError, setDateError] = useState('')
  const change = (patch: Partial<typeof value>) => {
    setTitleError('')
    setDateError('')
    setDraft('work:new', { ...value, ...patch, key: crypto.randomUUID() })
  }
  return (
    <Modal title="新建工作" onClose={onClose}>
      <form
        onSubmit={async (event) => {
          event.preventDefault()
          const validation = progressTitleError(value.title)
          setTitleError(validation || '')
          if (validation) return
          setError('')
          await submit(
            () =>
              createWork(
                {
                  title: value.title.trim(),
                  ...(value.description ? { body: documentFromText(value.description) } : {}),
                  dueDate: value.dueDate || null,
                },
                value.key,
              ),
            (work) => {
              window.dispatchEvent(new Event('paa-record-updated'))
              onSaved(work)
            },
            (failure) => {
              setTitleError(progressFieldErrors(failure).title ?? '')
              setDateError(progressFieldErrors(failure).dueDate ?? '')
              setError(failure as Error)
            },
          )
        }}
      >
        <fieldset disabled={busy}>
          <FormField
            label="工作事项"
            value={value.title ?? ''}
            required
            maxLength={200}
            error={titleError}
            autoFocus
            onChange={(event) => change({ title: event.target.value })}
          />
          <details>
            <summary>补充说明与日期（选填）</summary>
            <label>
              工作说明
              <textarea
                rows={3}
                value={value.description ?? ''}
                maxLength={12000}
                onChange={(event) => change({ description: event.target.value })}
              />
            </label>
            <FormField
              label="截止日期（选填）"
              error={dateError}
              type="date"
              max="9999-12-31"
              value={value.dueDate ?? ''}
              onChange={(event) => change({ dueDate: event.target.value })}
            />
          </details>
        </fieldset>
        <ErrorNotice>{error}</ErrorNotice>
        <div className={layout['form-actions']}>
          <button type="button" onClick={onClose}>
            稍后继续
          </button>
          <BusyButton busy={busy} className={controls.primary}>
            创建工作
          </BusyButton>
        </div>
      </form>
    </Modal>
  )
}
