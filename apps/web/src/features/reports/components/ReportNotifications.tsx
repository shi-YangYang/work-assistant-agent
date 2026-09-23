import controlsStyles from '../../../styles/controls.module.css'
import layoutStyles from '../../../styles/layout.module.css'
import styles from './ReportNotifications.module.css'
import type { NotificationPage } from '@paa/api-contracts'
import { Empty } from '@web/components/Empty'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Modal } from '@web/components/Modal'
import { markNotificationRead, notificationsPath } from '@web/features/reports/api/requests'
import { obligationTarget, reportDeadline } from '@web/features/reports/utils/obligations'
import { useResource } from '@web/hooks/useResource'
import { useWorkspace } from '@web/lib/workspace'
import { Bell } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'

export function ReportNotifications() {
  const { identity, drafts } = useWorkspace()
  const [open, setOpen] = useState(false)
  const [cursor, setCursor] = useState('0')
  const [failure, setFailure] = useState<Error | string>('')
  const navigate = useNavigate()
  const list = useResource<NotificationPage>(notificationsPath(identity, cursor), 30000)
  const refresh = list.refresh
  useEffect(() => {
    window.addEventListener('focus', refresh)
    return () => window.removeEventListener('focus', refresh)
  }, [refresh])
  if (identity.member.role !== 'employee') return null
  return (
    <>
      <button
        className={`${controlsStyles['icon-button']} ${styles['notification-launch']}`}
        aria-label={`汇报通知${list.data?.unread ? `，${list.data.unread} 条未读` : ''}`}
        title="汇报通知"
        onClick={() => {
          setOpen(true)
          list.refresh()
        }}
      >
        <Bell size={19} />
        {!!list.data?.unread && (
          <span className={styles['notification-count']}>
            {list.data.unread > 99 ? '99+' : list.data.unread}
          </span>
        )}
      </button>
      {open && (
        <Modal title="汇报通知" onClose={() => setOpen(false)}>
          <ErrorNotice retry={list.refresh}>{failure || list.error}</ErrorNotice>
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
                      try {
                        await markNotificationRead(item, {})
                        list.refresh()
                        setOpen(false)
                        navigate(obligationTarget(item.obligation))
                      } catch (error) {
                        setFailure(error as Error)
                      }
                    }}
                  >
                    <strong>
                      {item.obligation.kind === 'daily' ? '日报' : '周报'} ·{' '}
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
                        try {
                          await markNotificationRead(item, {})
                          list.refresh()
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
        </Modal>
      )}
    </>
  )
}
