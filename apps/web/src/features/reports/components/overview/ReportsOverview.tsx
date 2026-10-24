import { PageHeader } from '@web/components/layout/page-header/PageHeader'
import layoutStyles from '../../../../styles/layout.module.css'
import controlsStyles from '../../../../styles/controls.module.css'
import utilitiesStyles from '../../../../styles/utilities.module.css'
import recordLayoutStyles from '../../../../styles/patterns/RecordLayout.module.css'
import statusStyles from '../../../../styles/patterns/Status.module.css'
import styles from './ReportsOverview.module.css'
import type { Report, Rules } from '@paa/api-contracts'
import { BusyButton } from '@web/components/actions/BusyButton'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { ActionNotice } from '@web/components/feedback/ActionNotice'
import { isCancelled } from '@web/api/client'
import { Modal } from '@web/components/overlays/Modal'
import { RecordEmpty } from '@web/components/content/RecordEmpty'
import { generateReport, reportListPath, reportRulesPath } from '@web/features/reports/api/requests'
import { ReportActions } from '@web/features/reports/components/overview/ReportActions'
import { ReportObligations } from '@web/features/reports/components/overview/ReportObligations'
import { usePagedResource } from '@web/hooks/usePagedResource'
import { useResource } from '@web/hooks/useResource'
import { useWorkspace } from '@web/lib/workspace'
import { dateLabel, todayIn } from '@web/utils/date'
import { customRangeError } from '@web/utils/date-range'
import { detailState } from '@web/utils/navigation'
import { timezoneLabel } from '@web/utils/timezones'
import { CalendarDays, ChevronRight, FileText, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router'

function reportingPeriod(date: string) {
  if (customRangeError(date, date)) return null
  const start = new Date(`${date}T00:00:00Z`)
  start.setUTCDate(start.getUTCDate() - ((start.getUTCDay() + 6) % 7))
  const end = new Date(start)
  end.setUTCDate(end.getUTCDate() + 6)
  const range = { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) }
  return customRangeError(range.start, range.end) ? null : range
}

export function ReportsPage() {
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const kind = 'weekly' as const
  const todo = params.get('view') !== 'all'
  const { data, error, refresh, loadMore, loading } = usePagedResource<Report>(
    reportListPath(todo, kind),
    'period',
    2000,
  )
  const rules = useResource<Rules>(reportRulesPath())
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<{ period: string; error: Error | string } | null>(null)
  const [showRules, setShowRules] = useState(false)
  const { notify } = useWorkspace()
  const today = todayIn(rules.data?.timezone ?? 'Asia/Shanghai')
  const selectedDate = params.get('date') || today
  const period = reportingPeriod(selectedDate)
  const selectionKey = `${kind}:${selectedDate}:${todo}`
  const [failurePeriod, setFailurePeriod] = useState(selectionKey)
  if (failurePeriod !== selectionKey) {
    setFailurePeriod(selectionKey)
    setFailure(null)
  }
  const changeSelection = (next: Record<string, string>) => {
    setFailure(null)
    setParams(next)
  }
  const changeDate = (date: string) => {
    changeSelection({ kind, date, view: 'all' })
  }
  return (
    <div
      className={`${layoutStyles['page']} ${recordLayoutStyles['records-page']}`}
      data-scroll-container
    >
      <PageHeader
        title="我的报告"
        className={styles['report-header']}
        actions={
          <button onClick={() => setShowRules(true)}>
            <CalendarDays size={16} />
            汇报安排
          </button>
        }
      />
      {params.get('kind') === 'daily' && <p role="status">正式日报已取消，现显示周报。</p>}
      <div className={recordLayoutStyles['records-surface']}>
        <div className={recordLayoutStyles['records-navigation']}>
          <div
            className={`${layoutStyles['tabs']} ${recordLayoutStyles['slot-tabs']} ${styles['report-view-tabs']}`}
          >
            <button
              aria-pressed={todo}
              data-active={todo}
              onClick={() => changeSelection({ kind, view: 'todo' })}
            >
              汇报待办
            </button>
            <button
              aria-pressed={!todo}
              data-active={!todo}
              onClick={() => changeSelection({ kind, view: 'all' })}
            >
              全部报告
            </button>
          </div>
        </div>
        {!todo && (
          <div className={`${recordLayoutStyles['records-toolbar']} ${styles['report-generate']}`}>
            <div className={styles['period-controls']}>
              <label
                className={`${recordLayoutStyles['record-date-field']} ${styles['period-date']}`}
              >
                <span>{'汇报周期'}</span>
                <input
                  type="date"
                  aria-label="选择周报所在周"
                  aria-describedby="report-period-range"
                  min="0001-01-01"
                  max="9999-12-30"
                  value={selectedDate}
                  onClick={(event) => {
                    try {
                      event.currentTarget.showPicker?.()
                    } catch {
                      /* Native picker unavailable. */
                    }
                  }}
                  onChange={(e) => changeDate(e.target.value)}
                />
              </label>
              {
                <div className={styles['period-shortcuts']} aria-label="快捷选择汇报周期">
                  <button type="button" onClick={() => changeDate(today)}>
                    本周
                  </button>
                </div>
              }
            </div>
            <BusyButton
              busy={busy}
              disabled={!period}
              className={controlsStyles['primary']}
              onClick={async () => {
                setBusy(true)
                setFailure(null)
                try {
                  await generateReport({ kind, date: selectedDate }, crypto.randomUUID())
                  refresh()
                  notify('已准备报告，生成状态会自动更新')
                } catch (e) {
                  if (!isCancelled(e)) setFailure({ period: selectionKey, error: e as Error })
                } finally {
                  setBusy(false)
                }
              }}
            >
              <Sparkles size={16} />
              生成周报
            </BusyButton>
            {period && (
              <span id="report-period-range" className={styles['period-range']} role="status">
                {period.start} — {period.end}（周一至周日）
              </span>
            )}
          </div>
        )}
        <ErrorNotice className={recordLayoutStyles['record-notice']} retry={refresh}>
          {error}
        </ErrorNotice>
        <ActionNotice>{failure?.period === selectionKey ? failure.error : null}</ActionNotice>
        {todo ? (
          <ReportObligations />
        ) : (
          <div className={recordLayoutStyles['records-results']} aria-label="报告列表">
            {data?.items.length ? (
              <div className={recordLayoutStyles['record-list']}>
                {data.items.map((report) => (
                  <div
                    className={`${recordLayoutStyles['record-row']} ${recordLayoutStyles['report-row']}`}
                    key={report.id}
                  >
                    <Link
                      to={`/reports/${report.id}`}
                      state={detailState(location)}
                      className={`${recordLayoutStyles['record-main']} ${recordLayoutStyles['report-entry-link']}`}
                    >
                      <span className={recordLayoutStyles['record-type-icon']} aria-hidden="true">
                        <FileText size={21} />
                      </span>
                      <div className={recordLayoutStyles['record-main']}>
                        <h3>
                          周报 ·{' '}
                          <span className={recordLayoutStyles['record-period']}>
                            {report.period}
                          </span>
                          {
                            <>
                              {' '}
                              —{' '}
                              <span className={recordLayoutStyles['record-period']}>
                                {report.periodEnd}
                              </span>
                            </>
                          }
                        </h3>
                        <p>
                          <span
                            className={statusStyles['status']}
                            data-status={report.publishedRevision ? 'submitted' : 'draft'}
                          >
                            {report.publishedRevision
                              ? `已提交第 ${report.publishedRevision} 版${report.revision !== report.publishedRevision ? ' · 有未提交更正' : ''}`
                              : '草稿'}
                          </span>
                        </p>
                        <small>
                          {report.job?.state === 'running' || report.job?.state === 'queued'
                            ? '正在整理'
                            : ''}
                          {report.job?.error ? '生成未完成' : ''}
                        </small>
                      </div>
                      <time className={recordLayoutStyles['record-updated']}>
                        {dateLabel(report.updatedAt)}
                      </time>
                      <ChevronRight size={18} />
                    </Link>
                    <ReportActions report={report} onDeleted={refresh} />
                  </div>
                ))}
                {data.nextCursor && (
                  <button
                    className={recordLayoutStyles['records-load-more']}
                    disabled={loading}
                    onClick={loadMore}
                  >
                    加载更早报告
                  </button>
                )}
              </div>
            ) : data ? (
              <RecordEmpty icon={<FileText size={27} />} title="还没有周报">
                选择上方{'汇报周期'}生成草稿，整理后即可提交。
              </RecordEmpty>
            ) : (
              !error && (
                <p className={recordLayoutStyles['records-loading']} role="status">
                  正在读取报告…
                </p>
              )
            )}
          </div>
        )}
      </div>
      {showRules && (
        <Modal
          title="我的汇报安排"
          className={styles['schedule-dialog']}
          bodyClassName={styles['schedule-body']}
          onClose={() => setShowRules(false)}
        >
          {rules.data ? (
            <>
              <div className={styles['schedule-heading']}>
                <span className={styles['schedule-icon']} aria-hidden="true">
                  <CalendarDays size={22} />
                </span>
                <div className={styles['schedule-title']}>
                  <h3>周报</h3>
                  <span className={styles['schedule-badge']}>
                    {rules.data.weekly.enabled ? '自动生成' : '手动生成'}
                  </span>
                </div>
              </div>
              {rules.data.weekly.enabled ? (
                <dl className={styles['schedule-details']}>
                  <div>
                    <dt>草稿生成</dt>
                    <dd>
                      {rules.data.weekly.days
                        .map((d) => ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][d])
                        .join('、')}
                      {' · '}
                      {rules.data.weekly.generateTime}
                    </dd>
                  </div>
                  <div>
                    <dt>提交截止</dt>
                    <dd>{rules.data.weekly.deadline} 前</dd>
                  </div>
                  <div>
                    <dt>站内提醒</dt>
                    <dd>
                      {rules.data.weekly.reminders === false
                        ? '已关闭'
                        : `草稿就绪、截止前 ${rules.data.weekly.beforeMinutes ?? 30} 分钟及逾期后`}
                    </dd>
                  </div>
                </dl>
              ) : (
                <p className={styles['schedule-description']}>
                  自动生成尚未启用，可在报告页手动生成周报。
                </p>
              )}
              <dl className={styles['schedule-meta']}>
                <div>
                  <dt>公司时区</dt>
                  <dd>{timezoneLabel(rules.data.timezone)}</dd>
                </div>
                {rules.data.effectivePeriods?.weekly && (
                  <div>
                    <dt>生效周期</dt>
                    <dd>{rules.data.effectivePeriods.weekly} 起的周期</dd>
                  </div>
                )}
              </dl>
            </>
          ) : rules.error ? (
            <ErrorNotice retry={rules.refresh}>{rules.error}</ErrorNotice>
          ) : (
            <p className={utilitiesStyles['muted']}>正在读取…</p>
          )}
        </Modal>
      )}
    </div>
  )
}
