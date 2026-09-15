import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router'
import { Bell, ChevronRight, ClipboardCheck } from 'lucide-react'
import type { NotificationPage, ObligationPage, ReportObligation } from '@paa/api-contracts'
import { useResource, write } from './api'
import { BusyButton, Empty, ErrorNotice, Modal } from './ui'
import { detailState } from './navigation'
import { useWorkspace } from './workspace'

export const obligationLabel = (state: ReportObligation['state']) =>
  ({ pending: '待提交', overdue: '已逾期', submitted: '已提交', cancelled: '已撤销' })[state]
export function reportDeadline(item: ReportObligation) {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: item.timezone,
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(item.deadlineAt))
}
export function obligationTarget(item: ReportObligation) {
  return item.reportId
    ? `/reports/${item.reportId}`
    : `/reports?view=todo&kind=${item.kind}&period=${item.period}`
}

export function ReportObligations({ team = false }: { team?: boolean }) {
  const [params, setParams] = useSearchParams()
  const location = useLocation()
  const navigate = useNavigate()
  const kind = params.get('kind') === 'weekly' ? 'weekly' : 'daily'
  const query = new URLSearchParams({ kind })
  for (const key of ['status', 'period', 'cursor']) {
    if (params.get(key)) query.set(key, params.get(key)!)
  }
  const list = useResource<ObligationPage>(
    `${team ? '/team' : ''}/report-obligations?${query}`,
    30000,
  )
  const [busy, setBusy] = useState<string | null>(null)
  const [failure, setFailure] = useState('')
  const refresh = list.refresh
  useEffect(() => {
    window.addEventListener('focus', refresh)
    return () => window.removeEventListener('focus', refresh)
  }, [refresh])
  const update = (values: Record<string, string>) => {
    const next = new URLSearchParams(params)
    next.delete('cursor')
    Object.entries(values).forEach(([key, value]) =>
      value ? next.set(key, value) : next.delete(key),
    )
    setParams(next)
  }
  return (
    <section className={team ? 'page' : 'report-obligations'} aria-label="汇报待办">
      {team && (
        <div className="page-heading">
          <h2>汇报情况</h2>
          <button onClick={list.refresh}>刷新</button>
        </div>
      )}
      <div className="toolbar obligation-filters">
        {team && (
          <select
            aria-label="报告类型"
            value={kind}
            onChange={(event) => update({ kind: event.target.value })}
          >
            <option value="daily">日报</option>
            <option value="weekly">周报</option>
          </select>
        )}
        <select
          aria-label="汇报状态"
          value={params.get('status') || ''}
          onChange={(event) => update({ status: event.target.value })}
        >
          <option value="">全部状态</option>
          <option value="pending">待提交</option>
          <option value="overdue">已逾期</option>
          <option value="submitted">已提交</option>
          <option value="cancelled">已撤销</option>
        </select>
        <input
          type="date"
          aria-label="汇报周期"
          value={params.get('period') || (team ? list.data?.period : '') || ''}
          onClick={(event) => event.currentTarget.showPicker?.()}
          onChange={(event) => update({ period: event.target.value })}
        />
        {params.get('period') && (
          <button onClick={() => update({ period: '' })}>{team ? '本期' : '全部周期'}</button>
        )}
      </div>
      {team && list.data && (
        <div className="metrics obligation-metrics">
          <div>
            <span>应提交</span>
            <strong>{list.data.counts.expected}</strong>
          </div>
          <div>
            <span>已提交</span>
            <strong>{list.data.counts.submitted}</strong>
          </div>
          <div>
            <span>未提交</span>
            <strong>
              {list.data.counts.pending}
              <small> · {list.data.counts.overdue} 已逾期</small>
            </strong>
          </div>
        </div>
      )}
      <ErrorNotice retry={list.refresh}>{failure || list.error}</ErrorNotice>
      {list.data?.items.length ? (
        <div className="record-list">
          {list.data.items.map((item) => (
            <div className="record-row obligation-row" key={item.id}>
              <ClipboardCheck size={20} aria-hidden="true" />
              <div className="record-main">
                <h3>
                  {team && `${item.name} · `}
                  {item.period}
                  {kind === 'weekly' ? ` — ${item.periodEnd}` : ''}
                </h3>
                <p>
                  截止 {reportDeadline(item)}{' '}
                  <span className={`status ${item.state}`}>{obligationLabel(item.state)}</span>
                </p>
                {item.submittedAt && (
                  <small>提交于 {new Date(item.submittedAt).toLocaleString('zh-CN')}</small>
                )}
                {!team && item.job && (
                  <small>
                    {item.job.state === 'queued'
                      ? '等待整理'
                      : item.job.state === 'running'
                        ? '正在整理'
                        : item.job.phase === 'empty'
                          ? '暂无已确认工作，可补充工作或手动填写'
                          : item.job.error
                            ? '生成未完成，可打开报告重试或手动填写'
                            : ''}
                  </small>
                )}
              </div>
              {item.reportId ? (
                <Link
                  className="button"
                  to={`/reports/${item.reportId}`}
                  state={detailState(location)}
                >
                  {item.state === 'submitted' ? '查看报告' : '打开报告'}
                  <ChevronRight size={16} />
                </Link>
              ) : !team && item.state !== 'cancelled' ? (
                <BusyButton
                  busy={busy === item.id}
                  onClick={async () => {
                    setBusy(item.id)
                    setFailure('')
                    try {
                      const result = await write<{ reportId: string }>(
                        `/report-obligations/${item.id}/prepare`,
                        {},
                        'POST',
                        crypto.randomUUID(),
                      )
                      navigate(`/reports/${result.reportId}`, { state: detailState(location) })
                    } catch (error) {
                      setFailure((error as Error).message)
                    } finally {
                      setBusy(null)
                    }
                  }}
                >
                  准备报告
                </BusyButton>
              ) : null}
            </div>
          ))}
        </div>
      ) : (
        list.data && <Empty title={team ? '本期没有汇报安排' : '暂无汇报待办'} />
      )}
      {(params.get('cursor') || list.data?.nextCursor) && (
        <div className="form-actions">
          <button
            disabled={!params.get('cursor')}
            onClick={() =>
              update({ cursor: String(Math.max(0, Number(params.get('cursor')) - 20)) })
            }
          >
            上一页
          </button>
          <button
            disabled={!list.data?.nextCursor}
            onClick={() => update({ cursor: list.data!.nextCursor! })}
          >
            下一页
          </button>
        </div>
      )}
    </section>
  )
}

export function ReportNotifications() {
  const { identity, drafts } = useWorkspace()
  const [open, setOpen] = useState(false)
  const [cursor, setCursor] = useState('0')
  const [failure, setFailure] = useState('')
  const navigate = useNavigate()
  const list = useResource<NotificationPage>(
    identity.member.role === 'employee' ? `/notifications?cursor=${cursor}` : null,
    30000,
  )
  const refresh = list.refresh
  useEffect(() => {
    window.addEventListener('focus', refresh)
    return () => window.removeEventListener('focus', refresh)
  }, [refresh])
  if (identity.member.role !== 'employee') return null
  return (
    <>
      <button
        className="icon-button notification-launch"
        aria-label={`汇报通知${list.data?.unread ? `，${list.data.unread} 条未读` : ''}`}
        title="汇报通知"
        onClick={() => {
          setOpen(true)
          list.refresh()
        }}
      >
        <Bell size={19} />
        {!!list.data?.unread && (
          <span className="notification-count">
            {list.data.unread > 99 ? '99+' : list.data.unread}
          </span>
        )}
      </button>
      {open && (
        <Modal title="汇报通知" onClose={() => setOpen(false)}>
          <ErrorNotice retry={list.refresh}>{failure || list.error}</ErrorNotice>
          {list.data?.items.length ? (
            <div className="notification-list">
              {list.data.items.map((item) => (
                <div className={`notification-item ${item.read ? '' : 'unread'}`} key={item.id}>
                  <button
                    className="notification-content"
                    onClick={async () => {
                      if (
                        drafts.recording &&
                        !window.confirm('离开工作助手会停止录音，并保留已录制内容。继续？')
                      )
                        return
                      try {
                        await write(`/notifications/${item.id}/read`, {})
                        list.refresh()
                        setOpen(false)
                        navigate(obligationTarget(item.obligation))
                      } catch (error) {
                        setFailure((error as Error).message)
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
                      className="text-button"
                      onClick={async () => {
                        try {
                          await write(`/notifications/${item.id}/read`, {})
                          list.refresh()
                        } catch (error) {
                          setFailure((error as Error).message)
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
            <div className="form-actions">
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
