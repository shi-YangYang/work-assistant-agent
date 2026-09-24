import layoutStyles from '../../../styles/layout.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import type { Progress } from '@paa/api-contracts'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Modal } from '@web/components/Modal'
import { createWork, progressFieldErrors } from '@web/features/work/api/requests'
import { ProgressFields } from '@web/features/work/components/ProgressFields'
import { progressTitleError } from '@web/features/work/utils/progress-edit'
import { useWorkspace } from '@web/lib/workspace'
import { useState } from 'react'

export function CreateWork({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const { drafts, setDraft } = useWorkspace()
  const draft = drafts['work:new'] as { content: Progress; key: string } | undefined
  const [initialKey] = useState(() => crypto.randomUUID())
  const content = draft?.content ?? {
    title: '',
    summary: '',
    status: 'in_progress' as const,
    blocker: '',
    nextStep: '',
    dueDate: null,
  }
  const key = draft?.key ?? initialKey
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<keyof Progress, string>>>({})
  return (
    <Modal title="新建工作" onClose={() => !busy && onClose()}>
      <form
        onSubmit={async (event) => {
          event.preventDefault()
          const title = progressTitleError(content.title)
          setFieldErrors({ title })
          if (title) return
          setBusy(true)
          setError('')
          // Preserve the same key through an uncertain network response and reopening.
          setDraft('work:new', { content, key })
          try {
            await createWork(content, key)
            setDraft('work:new', undefined)
            window.dispatchEvent(new Event('paa-record-updated'))
            onSaved()
          } catch (error) {
            setFieldErrors(progressFieldErrors(error))
            setError(error as Error)
          } finally {
            setBusy(false)
          }
        }}
      >
        <fieldset disabled={busy}>
          <ProgressFields
            value={content}
            errors={fieldErrors}
            change={(value) => {
              setFieldErrors({})
              setDraft('work:new', { content: value, key: crypto.randomUUID() })
            }}
          />
        </fieldset>
        <ErrorNotice>{error}</ErrorNotice>
        <div className={layoutStyles['form-actions']}>
          <button type="button" disabled={busy} onClick={onClose}>
            稍后继续
          </button>
          <BusyButton busy={busy} className={controlsStyles['primary']}>
            创建工作
          </BusyButton>
        </div>
      </form>
    </Modal>
  )
}
