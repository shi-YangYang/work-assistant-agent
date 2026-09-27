import type { VoiceprintCleanupSummary } from '@paa/api-contracts'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Modal } from '@web/components/Modal'
import { cleanupVoiceprints, voiceprintCleanupPath } from '@web/features/voiceprints/api/requests'
import { useResource } from '@web/hooks/useResource'
import { useWorkspace } from '@web/lib/workspace'
import { useState } from 'react'
import styles from '../styles/voiceprints.module.css'
import layoutStyles from '../../../styles/layout.module.css'

export function VoiceprintCleanup({ refresh }: { refresh: () => void }) {
  const summary = useResource<VoiceprintCleanupSummary>(voiceprintCleanupPath())
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  const { notify } = useWorkspace()
  const data = summary.data
  return (
    <section className={styles['cleanup-section']} aria-label="声纹资料清理">
      <div>
        <strong>资料清理</strong>
        <p>
          {data
            ? `遗留 ${data.legacy.voiceprints} 份声纹 · 待清理 ${data.pending} 项${data.failed ? ` · ${data.failed} 项需重试` : ''}`
            : '核对已删除账号的遗留资料'}
        </p>
      </div>
      <button
        onClick={() => {
          setError('')
          setOpen(true)
        }}
      >
        查看并清理
      </button>
      <ErrorNotice retry={summary.refresh}>{summary.error}</ErrorNotice>
      {open && (
        <CleanupPreview
          busy={busy}
          error={error}
          onClose={() => !busy && setOpen(false)}
          onConfirm={async () => {
            if (busy) return
            setBusy(true)
            setError('')
            try {
              const result = await cleanupVoiceprints()
              summary.refresh()
              refresh()
              setOpen(false)
              notify(
                result.pending || result.failed
                  ? '清理尚未全部完成，可稍后在资料清理中重试。'
                  : '遗留声纹资料已清理',
              )
            } catch (failure) {
              setError(failure as Error)
            } finally {
              setBusy(false)
            }
          }}
        />
      )}
    </section>
  )
}

function CleanupPreview({
  busy,
  error,
  onClose,
  onConfirm,
}: {
  busy: boolean
  error: Error | string
  onClose: () => void
  onConfirm: () => Promise<void>
}) {
  // Fetch on every opening so confirmation never relies on a stale page count.
  const preview = useResource<VoiceprintCleanupSummary>(voiceprintCleanupPath())
  const data = preview.data
  return (
    <Modal title="清理遗留声纹资料" onClose={onClose}>
      {data ? (
        <>
          <p>
            将清理 {data.legacy.members} 位已删除成员的 {data.legacy.voiceprints} 份声纹和{' '}
            {data.legacy.recordings} 份登记录音，并重试 {data.pending} 项待清理任务。
          </p>
          <p>停用成员、历史工作和报告保持不变。已离线的桌面副本不受影响。</p>
        </>
      ) : (
        !preview.error && <p role="status">正在读取清理范围…</p>
      )}
      <ErrorNotice retry={preview.refresh}>{error || preview.error}</ErrorNotice>
      <div className={layoutStyles['form-actions']}>
        <button disabled={busy} onClick={onClose}>
          取消
        </button>
        <BusyButton
          busy={busy}
          disabled={
            !data ||
            !!preview.error ||
            !(data.legacy.voiceprints || data.legacy.recordings || data.pending || data.failed)
          }
          onClick={() => void onConfirm()}
        >
          确认清理
        </BusyButton>
      </div>
    </Modal>
  )
}
