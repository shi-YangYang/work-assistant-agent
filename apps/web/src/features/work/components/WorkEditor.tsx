import type { Progress, Work } from '@paa/api-contracts'
import { BusyButton } from '@web/components/BusyButton'
import { ConflictRecovery } from '@web/components/ConflictRecovery'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Modal } from '@web/components/Modal'
import { readWork, updateWorkProgress } from '@web/features/work/api/requests'
import { ProgressFields } from '@web/features/work/components/ProgressFields'
import { useWorkspace } from '@web/lib/workspace'
import { useState } from 'react'

export function WorkEditor({
  work,
  onClose,
  onSaved,
}: {
  work: Work
  onClose: () => void
  onSaved: () => void
}) {
  const { drafts, setDraft } = useWorkspace()
  const key = `work:${work.id}`
  const stored = drafts[key] as { content: Progress; revision: number } | undefined
  const value = stored?.content ?? work
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  return (
    <Modal title="更正工作进展" onClose={onClose}>
      <form
        onSubmit={async (e) => {
          e.preventDefault()
          setBusy(true)
          try {
            const { title, summary, status, blocker, nextStep, dueDate } = value
            await updateWorkProgress(work, {
              title,
              summary,
              status,
              blocker,
              nextStep,
              dueDate,
              sourceIds: [],
              expectedRevision: stored?.revision ?? work.revision,
            })
            setDraft(key, undefined)
            window.dispatchEvent(new Event('paa-record-updated'))
            onSaved()
          } catch (e) {
            setError(e as Error)
          } finally {
            setBusy(false)
          }
        }}
      >
        <ProgressFields
          value={value}
          change={(content) =>
            setDraft(key, { content, revision: stored?.revision ?? work.revision })
          }
        />
        <ErrorNotice>{error}</ErrorNotice>
        {error && (
          <ConflictRecovery<Work>
            load={() => readWork(work)}
            render={(latest) => (
              <>
                <p>
                  {latest.title}：{latest.summary}
                </p>
                <p>{latest.blocker}</p>
                <p>{latest.nextStep}</p>
              </>
            )}
            keep={(latest) => {
              setDraft(key, { content: value, revision: latest.revision })
              setError('')
            }}
            replace={(latest) => {
              setDraft(key, { content: latest, revision: latest.revision })
              setError('')
            }}
          />
        )}
        <div className="form-actions">
          <button type="button" onClick={onClose}>
            稍后继续
          </button>
          <BusyButton busy={busy} className="primary">
            保存更正
          </BusyButton>
        </div>
      </form>
    </Modal>
  )
}
