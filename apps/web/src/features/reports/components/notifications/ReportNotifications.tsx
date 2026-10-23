import controlsStyles from '../../../../styles/controls.module.css'
import layoutStyles from '../../../../styles/layout.module.css'
import styles from './ReportNotifications.module.css'
import type { NotificationPage } from '@paa/api-contracts'
import { Empty } from '@web/components/feedback/Empty'
import { ErrorNoticeView as ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { ActionNotice } from '@web/components/feedback/ActionNotice'
import { markNotificationRead, notificationsPath } from '@web/features/reports/api/requests'
import { obligationTarget, reportDeadline } from '@web/features/reports/utils/obligations'
import { useResource } from '@web/hooks/useResource'
import { useWorkspace } from '@web/lib/workspace'
import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'

export function ReportNotifications({ active = true }: { active?: boolean }) {
  const { identity, drafts } = useWorkspace()
  const [params, setParams] = useSearchParams()
  const page = Math.max(1, Math.min(50001, Number(params.get('reminderPage')) || 1))
  const cursor = String((page - 1) * 20)
  const setCursor = (value: string) => {
    setFailure('')
    const next = new URLSearchParams(params)
    next.set('reminderPage', String(Number(value) / 20 + 1))
    setParams(next)
  }
  const [failure, setFailure] = useState<Error | string>('')
  const navigate = useNavigate()
  const list = useResource<NotificationPage>(notificationsPath(identity, cursor))
  const refresh = list.refresh
  useEffect(() => {
    if (active) refresh()
  }, [active, refresh])
  const sync = () => {
    list.refresh()
    window.dispatchEvent(new Event('paa-notifications-changed'))
  }
  if (identity.member.role !== 'employee') return <Empty title="暂无提醒" />
  return (
    <div>
      {!list.data && !list.error && <p>正在读取提醒…</p>}
      <ErrorNotice retry={list.refresh}>{list.error}</ErrorNotice>
      <ActionNotice>{active ? failure : null}</ActionNotice>
      {list.data?.items.length ? (
        <div className={styles['notification-list']}>
          {list.data.items.map((item) => (
            <div className={styles['notification-item']} data-unread={!item.read} key={item.id}>
              <button
                className={styles['notification-content']}
                onClick={async () => {
                  if (
                    drafts.recording &&
                    !window.confirm('离开工作助手会停止录音，并保留已录制内容。继续？')
                  )
                    return
                  setFailure('')
                  try {
                    await markNotificationRead(item, {})
                    sync()
                    navigate(obligationTarget(item.obligation))
                  } catch (error) {
                    setFailure(error as Error)
                  }
                }}
              >
                <strong>
                  {'周报'} ·{' '}
                  {{ ready: '草稿已就绪', due: '即将截止', overdue: '待补交' }[item.stage]}
                </strong>
                <span>
                  {item.obligation.period}
                  {item.obligation.kind === 'weekly' ? ` — ${item.obligation.periodEnd}` : ''}
                </span>
                <small>截止 {reportDeadline(item.obligation)}</small>
              </button>
              {!item.read && (
                <button
                  className={`${controlsStyles['text-button']}`}
                  onClick={async () => {
                    setFailure('')
                    try {
                      await markNotificationRead(item, {})
                      sync()
                    } catch (error) {
                      setFailure(error as Error)
                    }
                  }}
                >
                  已读
                </button>
              )}
            </div>
          ))}
        </div>
      ) : (
        list.data && <Empty title="暂无汇报通知" />
      )}
      {(cursor !== '0' || list.data?.nextCursor) && (
        <div className={layoutStyles['form-actions']}>
          <button
            disabled={cursor === '0'}
            onClick={() => setCursor(String(Math.max(0, Number(cursor) - 20)))}
          >
            上一页
          </button>
          <button
            disabled={!list.data?.nextCursor}
            onClick={() => setCursor(list.data!.nextCursor!)}
          >
            下一页
          </button>
        </div>
      )}
    </div>
  )
}
