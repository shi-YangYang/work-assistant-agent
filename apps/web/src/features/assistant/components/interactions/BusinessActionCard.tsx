import utilitiesStyles from '../../../../styles/utilities.module.css'
import layoutStyles from '../../../../styles/layout.module.css'
import controlsStyles from '../../../../styles/controls.module.css'
import styles from './BusinessActionCard.module.css'
import type { BusinessAction, Progress, ReportContent } from '@paa/api-contracts'
import { BusyButton } from '@web/components/actions/BusyButton'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { Status } from '@web/components/feedback/Status'
import { resolveBusinessAction } from '@web/features/assistant/api/requests'
import { detailState } from '@web/utils/navigation'
import { AlertCircle, CheckCircle2, Clock3 } from 'lucide-react'
import { useLayoutEffect, useRef, useState } from 'react'
import { epoch } from '@web/api/client'
import type { TaskContinuation } from '../../api/interactions'
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
    <div className={styles['business-action-preview']}>
      {Object.entries(workLabels)
        .filter(
          ([key]) =>
            action.details?.[key as keyof Progress] ||
            action.changedFields?.includes(key as keyof Progress),
        )
        .map(([key, label]) => (
          <section key={key}>
            <strong>{label}</strong>
            <p className={utilitiesStyles['preserve']}>
              {action.details?.[key as keyof Progress] || '已清空'}
            </p>
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
  onContinuation,
}: {
  onContinuation?: (continuation?: TaskContinuation) => void
  action: BusinessAction
  refresh: () => void
}) {
  const location = useLocation()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  const generation = epoch
  const active = useRef(false)
  const submitting = useRef(false)
  useLayoutEffect(() => {
    active.current = true
    return () => {
      active.current = false
    }
  }, [])
  const [saved, setSaved] = useState<BusinessAction | null>(null)
  const current =
    saved && saved.revision > action.revision && !['unavailable', 'conflict'].includes(action.state)
      ? saved
      : action
  const Icon =
    current.state === 'succeeded'
      ? CheckCircle2
      : ['pending', 'running'].includes(current.state)
        ? Clock3
        : AlertCircle
  const respond = async (choice: 'confirm' | 'cancel') => {
    if (submitting.current) return
    submitting.current = true
    setBusy(true)
    setError('')
    try {
      const result = await resolveBusinessAction(current, choice, {
        expectedRevision: current.revision,
      })
      if (!active.current || generation !== epoch) return
      setSaved(result)
      onContinuation?.(result.continuation ?? undefined)
      refresh()
      window.dispatchEvent(new Event('paa-record-updated'))
    } catch (e) {
      if (!active.current || generation !== epoch) return
      setError(e as Error)
      refresh()
    } finally {
      submitting.current = false
      if (active.current && generation === epoch) setBusy(false)
    }
  }
  return (
    <section
      className={styles['business-action-card']}
      data-status={current.state}
      aria-label={`${current.label} · ${actionStateLabel(current)}`}
    >
      <div className={styles['business-action-heading']}>
        <Icon size={18} />
        <strong>{current.label}</strong>
        <span>{busy ? '正在处理' : actionStateLabel(current)}</span>
      </div>
      {(current.title || current.preview?.title) && (
        <h4>{current.title ?? current.preview?.title}</h4>
      )}
      {current.details?.status && <Status value={current.details.status} />}
      {current.details && !current.preview?.changes && <WorkActionDetails action={current} />}
      {current.preview?.changes && (
        <ActionChanges before={current.preview.before} changes={current.preview.changes} />
      )}
      {current.message && <p className={utilitiesStyles['muted']}>{current.message}</p>}
      {current.preview?.content && (
        <div className={styles['business-action-preview']}>
          {Object.entries(reportLabels).map(([key, label]) => (
            <section key={key}>
              <strong>{label}</strong>
              <p className={utilitiesStyles['preserve']}>
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
        <p className={`${utilitiesStyles['muted']} ${utilitiesStyles['small-text']}`}>
          本次操作结果：第 {current.objectRevision} 版
        </p>
      )}
      <div className={`${layoutStyles['card-actions']} ${styles['slot-card-actions']}`}>
        {current.state === 'running' && (
          <button className={controlsStyles['text-button']} onClick={refresh}>
            刷新状态
          </button>
        )}
        {current.objectId && (
          <Link
            className={`${controlsStyles['text-button']}`}
            to={`/${current.objectType === 'work' ? 'work' : 'reports'}/${current.objectId}`}
            state={detailState(location)}
          >
            查看当前{current.objectType === 'work' ? '工作' : '报告'}
          </Link>
        )}
        {busy && <span role="status">正在处理…</span>}
        {current.canConfirm && !busy && (
          <>
            <button disabled={busy} onClick={() => void respond('cancel')}>
              取消
            </button>
            <BusyButton
              busy={busy}
              className={
                current.action.startsWith('delete_')
                  ? controlsStyles['danger']
                  : controlsStyles['primary']
              }
              onClick={() => void respond('confirm')}
            >
              {current.confirmLabel ??
                (current.action.startsWith('delete_')
                  ? '确认删除'
                  : current.action === 'submit_report'
                    ? '确认提交'
                    : '确认执行')}
            </BusyButton>
          </>
        )}
      </div>
    </section>
  )
}

const fieldLabels: Record<string, string> = {
  ...workLabels,
  ...reportLabels,
  title: '标题',
  status: '状态',
  content: '报告内容',
  kind: '报告类型',
  period: '开始日期',
  periodEnd: '结束日期',
  summary: '摘要',
}
function previewValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '未设置'
  if (Array.isArray(value)) return value.map(previewValue).join('、')
  if (typeof value === 'object')
    return Object.entries(value)
      .map(([key, item]) => `${fieldLabels[key] ?? key}：${previewValue(item)}`)
      .join('\n')
  return (
    (
      {
        in_progress: '进行中',
        done: '已完成',
        blocked: '有阻碍',
        daily: '日报',
        weekly: '周报',
      } as Record<string, string>
    )[String(value)] ?? String(value)
  )
}
function ActionChanges({
  before,
  changes,
}: {
  before?: Record<string, unknown>
  changes: Record<string, unknown>
}) {
  return (
    <div className={styles['business-action-preview']}>
      {Object.entries(changes).map(([key, value]) => (
        <section key={key}>
          <strong>{fieldLabels[key] ?? key}</strong>
          {before && Object.hasOwn(before, key) && (
            <p className={`${utilitiesStyles.preserve} ${styles.before}`}>
              原内容：{previewValue(before[key])}
            </p>
          )}
          <p className={utilitiesStyles.preserve}>{previewValue(value)}</p>
        </section>
      ))}
    </div>
  )
}
