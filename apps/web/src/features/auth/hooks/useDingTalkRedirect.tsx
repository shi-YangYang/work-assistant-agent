import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Modal } from '@web/components/Modal'
import { startDingTalkRedirect, type DingTalkAction } from '@web/features/auth/api/requests'
import { dingtalkDraftSummary, officialDingTalkUrl } from '@web/features/auth/utils/dingtalk-flow'
import { copyText } from '@web/lib/diagnostics'
import type { DraftStore } from '@web/lib/workspace'
import { Workspace } from '@web/lib/workspace'
import { useContext, useState } from 'react'

export function useDingTalkRedirect(drafts?: DraftStore) {
  const workspace = useContext(Workspace)
  const [pending, setPending] = useState<{ action: DingTalkAction; body: unknown } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  const [copied, setCopied] = useState('')
  const summary = dingtalkDraftSummary(drafts ?? workspace?.drafts ?? {})
  const proceed = async (action: DingTalkAction, body: unknown) => {
    setBusy(true)
    setError('')
    try {
      const result = await startDingTalkRedirect(action, body)
      window.location.assign(officialDingTalkUrl(result.url))
    } catch (e) {
      setError(e as Error)
    } finally {
      setBusy(false)
    }
  }
  const launch = (action: DingTalkAction, body: unknown = {}) => {
    if (summary.hasDrafts) setPending({ action, body })
    else void proceed(action, body)
  }
  const guard = (
    <>
      {!pending && <ErrorNotice>{error}</ErrorNotice>}
      {pending && (
        <Modal title="前往钉钉前保留草稿" onClose={() => setPending(null)}>
          <p>
            当前还有未发送或未保存的内容。离开后这些内容会丢失；你可以取消并返回密码登录，或先复制文字再继续。
          </p>
          {summary.files > 0 && <p>还有 {summary.files} 个附件；离开后需要重新选择附件。</p>}
          {summary.text && (
            <textarea aria-label="待保留的聊天文字" readOnly value={summary.text} rows={5} />
          )}
          {copied && <p role="status">{copied}</p>}
          <ErrorNotice retry={busy ? undefined : () => void proceed(pending.action, pending.body)}>
            {error}
          </ErrorNotice>
          <div className="form-actions">
            <button type="button" onClick={() => setPending(null)}>
              取消并返回
            </button>
            {summary.text && (
              <button
                type="button"
                onClick={() =>
                  void copyText(summary.text).then(
                    () => setCopied('文字已复制'),
                    () => setCopied('复制失败，请手动选择上方文字。'),
                  )
                }
              >
                复制文字
              </button>
            )}
            <BusyButton
              type="button"
              busy={busy}
              onClick={() => void proceed(pending.action, pending.body)}
            >
              确认离开并前往钉钉
            </BusyButton>
          </div>
        </Modal>
      )}
    </>
  )
  return { launch, busy, guard }
}
