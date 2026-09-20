import type { BusinessAction, Progress, ReportContent } from '@paa/api-contracts'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Status } from '@web/components/Status'
import { resolveBusinessAction } from '@web/features/assistant/api/requests'
import { detailState } from '@web/utils/navigation'
import { AlertCircle, CheckCircle2, Clock3 } from 'lucide-react'
import { useState } from 'react'
import { Link, useLocation } from 'react-router'

const reportLabels: Record<keyof ReportContent, string> = {
  completed: '完成的工作',
  ongoing: '进行中的工作',
  blockers: '问题与阻碍',
  next: '下一步计划',
}

const workLabels: Partial<Record<keyof Progress, string>> = {
  summary: '摘要',
  blocker: '阻碍',
  nextStep: '下一步',
  dueDate: '截止日期',
}

export function WorkActionDetails({ action }: { action: BusinessAction }) {
  return (
    <div className="business-action-preview">
      {Object.entries(workLabels)
        .filter(
          ([key]) =>
            action.details?.[key as keyof Progress] ||
            action.changedFields?.includes(key as keyof Progress),
        )
        .map(([key, label]) => (
          <section key={key}>
            <strong>{label}</strong>
            <p className="preserve">{action.details?.[key as keyof Progress] || '已清空'}</p>
          </section>
        ))}
    </div>
  )
}

export const actionStateLabel = (action: BusinessAction) => {
  if (action.state === 'succeeded') return '已完成'
  if (action.state === 'pending') return '等待确认'
  if (action.state === 'cancelled') return '已取消'
  if (action.state === 'running')
    return action.job && ['failed', 'awaiting_retry', 'cancelled'].includes(action.job.state)
      ? '尚未生成'
      : '正在生成'
  if (action.state === 'conflict') return '内容已变化'
  if (action.state === 'unavailable') return '记录不可用'
  return '未完成'
}

export function BusinessActionCard({
  action,
  refresh,
}: {
  action: BusinessAction
  refresh: () => void
}) {
  const location = useLocation()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  const [saved, setSaved] = useState<BusinessAction | null>(null)
  const current = saved && saved.revision > action.revision ? saved : action
  const Icon =
    current.state === 'succeeded'
      ? CheckCircle2
      : ['pending', 'running'].includes(current.state)
        ? Clock3
        : AlertCircle
  const respond = async (choice: 'confirm' | 'cancel') => {
    setBusy(true)
    setError('')
    try {
      const result = await resolveBusinessAction(current, choice, {
        expectedRevision: current.revision,
      })
      setSaved(result)
      refresh()
      window.dispatchEvent(new Event('paa-record-updated'))
    } catch (e) {
      setError(e as Error)
      refresh()
    } finally {
      setBusy(false)
    }
  }
  return (
    <section
      className={`business-action-card business-action-${current.state}`}
      aria-label={`${current.label} · ${actionStateLabel(current)}`}
    >
      <div className="business-action-heading">
        <Icon size={18} />
        <strong>{current.label}</strong>
        <span>{actionStateLabel(current)}</span>
      </div>
      {(current.title || current.preview?.title) && (
        <h4>{current.title ?? current.preview?.title}</h4>
      )}
      {current.details?.status && <Status value={current.details.status} />}
      {current.details && <WorkActionDetails action={current} />}
      {current.message && <p className="muted">{current.message}</p>}
      {current.preview?.content && (
        <div className="business-action-preview">
          {Object.entries(reportLabels).map(([key, label]) => (
            <section key={key}>
              <strong>{label}</strong>
              <p className="preserve">
                {current.preview?.content?.[key as keyof ReportContent] || '暂无记录'}
              </p>
            </section>
          ))}
        </div>
      )}
      {current.action.startsWith('delete_') && current.canConfirm && (
        <p>
          {current.action === 'delete_work'
            ? '删除工作后，原始消息与报告中的历史记录会保留。'
            : `将删除报告，同时清理 ${current.impact?.messages ?? 0} 条原始消息、${current.impact?.attachments ?? 0} 个附件。其他独立工作与报告保留。`}{' '}
          此操作不能撤销。
        </p>
      )}
      <ErrorNotice>{error}</ErrorNotice>
      {current.objectRevision && (
        <p className="muted small-text">本次操作结果：第 {current.objectRevision} 版</p>
      )}
      <div className="card-actions">
        {current.objectId && (
          <Link
            className="button text-button"
            to={`/${current.objectType === 'work' ? 'work' : 'reports'}/${current.objectId}`}
            state={detailState(location)}
          >
            查看当前{current.objectType === 'work' ? '工作' : '报告'}
          </Link>
        )}
        {current.canConfirm && (
          <>
            <button disabled={busy} onClick={() => void respond('cancel')}>
              取消
            </button>
            <BusyButton
              busy={busy}
              className={current.action.startsWith('delete_') ? 'danger' : 'primary'}
              onClick={() => void respond('confirm')}
            >
              {current.action.startsWith('delete_') ? '确认删除' : '确认提交'}
            </BusyButton>
          </>
        )}
      </div>
    </section>
  )
}
