import layoutStyles from '../../../styles/layout.module.css'
import recordLayoutStyles from '../../../components/RecordLayout.module.css'
import statusStyles from '../../../components/Status.module.css'
import styles from './ReportObligations.module.css'
import type { ObligationPage } from '@paa/api-contracts'
import { BusyButton } from '@web/components/BusyButton'
import { Empty } from '@web/components/Empty'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { RecordEmpty } from '@web/components/RecordEmpty'
import { prepareReport, reportObligationsPath } from '@web/features/reports/api/requests'
import { obligationLabel, reportDeadline } from '@web/features/reports/utils/obligations'
import { useResource } from '@web/hooks/useResource'
import { detailState } from '@web/utils/navigation'
import { ChevronRight, ClipboardCheck } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router'

export function ReportObligations({ team = false }: { team?: boolean }) {
  const [params, setParams] = useSearchParams()
  const location = useLocation()
  const navigate = useNavigate()
  const kind = params.get('kind') === 'weekly' ? 'weekly' : 'daily'
  const query = new URLSearchParams({ kind })
  for (const key of ['status', 'period', 'cursor']) {
    if (params.get(key)) query.set(key, params.get(key)!)
  }
  const list = useResource<ObligationPage>(reportObligationsPath(team, query), 30000)
  const [busy, setBusy] = useState<string | null>(null)
  const [failure, setFailure] = useState<Error | string>('')
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
    <section
      className={team ? layoutStyles['page'] : styles['report-obligations']}
      data-scroll-container={team || undefined}
      data-embedded={!team}
      aria-label="汇报待办"
    >
      {team && (
        <div className={`${layoutStyles['page-heading']}`}>
          <h2>汇报情况</h2>
          <button onClick={list.refresh}>刷新</button>
        </div>
      )}
      <div
        className={`${layoutStyles['toolbar']} ${styles['obligation-filters']} ${team ? '' : recordLayoutStyles['records-toolbar']}`}
      >
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
        <label
          className={`${recordLayoutStyles['record-date-field']} ${styles['slot-record-date-field']}`}
        >
          <span>汇报周期</span>
          <input
            type="date"
            aria-label="汇报周期"
            value={params.get('period') || (team ? list.data?.period : '') || ''}
            onClick={(event) => {
              try {
                event.currentTarget.showPicker?.()
              } catch {
                /* Native picker unavailable. */
              }
            }}
            onChange={(event) => update({ period: event.target.value })}
          />
        </label>
        {params.get('period') && (
          <button onClick={() => update({ period: '' })}>{team ? '本期' : '全部周期'}</button>
        )}
      </div>
      {team && list.data && (
        <div className={`${layoutStyles['metrics']} ${styles['obligation-metrics']}`}>
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
      <ErrorNotice className={styles['obligation-notice']} retry={list.refresh}>
        {failure || list.error}
      </ErrorNotice>
      <div className={team ? '' : recordLayoutStyles['records-results']}>
        {!list.data && !list.error && (
          <p className={recordLayoutStyles['records-loading']} role="status">
            正在读取汇报待办…
          </p>
        )}
        {list.data?.items.length ? (
          <div className={recordLayoutStyles['record-list']}>
            {list.data.items.map((item) => (
              <div
                className={`${recordLayoutStyles['record-row']} ${styles['obligation-row']}`}
                key={item.id}
              >
                <span className={recordLayoutStyles['record-type-icon']} aria-hidden="true">
                  <ClipboardCheck size={20} />
                </span>
                <div
                  className={`${recordLayoutStyles['record-main']} ${styles['slot-record-main']}`}
                >
                  <h3>
                    {team && `${item.name} · `}
                    {!team && (kind === 'weekly' ? '周报 · ' : '日报 · ')}
                    <span className={recordLayoutStyles['record-period']}>{item.period}</span>
                    {kind === 'weekly' && (
                      <>
                        {' '}
                        —{' '}
                        <span className={recordLayoutStyles['record-period']}>
                          {item.periodEnd}
                        </span>
                      </>
                    )}
                  </h3>
                  <p>
                    截止 {reportDeadline(item)}{' '}
                    <span
                      className={`${statusStyles['status']} ${styles['obligation-status']}`}
                      data-status={item.state}
                    >
                      {obligationLabel(item.state)}
                    </span>
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
                    className={styles['obligation-link']}
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
                        const result = await prepareReport(item, {}, crypto.randomUUID())
                        navigate(`/reports/${result.reportId}`, { state: detailState(location) })
                      } catch (error) {
                        setFailure(error as Error)
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
          list.data &&
          (team ? (
            <Empty title="本期没有汇报安排" />
          ) : (
            <RecordEmpty
              icon={<ClipboardCheck size={27} />}
              title={
                params.get('status') || params.get('period') ? '没有符合条件的汇报' : '暂无汇报待办'
              }
              action={
                params.get('status') || params.get('period') ? (
                  <button onClick={() => update({ status: '', period: '' })}>重置筛选</button>
                ) : (
                  <Link to={`/reports?kind=${kind}&view=all`}>
                    查看全部报告
                    <ChevronRight size={15} />
                  </Link>
                )
              }
            >
              {params.get('status') || params.get('period')
                ? '试试其他状态或汇报周期。'
                : `当前没有需要提交的${kind === 'daily' ? '日报' : '周报'}。`}
            </RecordEmpty>
          ))
        )}
      </div>
      {(params.get('cursor') || list.data?.nextCursor) && (
        <div className={`${layoutStyles['form-actions']} ${styles['slot-form-actions']}`}>
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
