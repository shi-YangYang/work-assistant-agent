import layoutStyles from '../../../styles/layout.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import utilitiesStyles from '../../../styles/utilities.module.css'
import recordLayoutStyles from '../../../components/RecordLayout.module.css'
import statusStyles from '../../../components/Status.module.css'
import styles from './ReportsOverview.module.css'
import type { Report, Rules } from '@paa/api-contracts'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Modal } from '@web/components/Modal'
import { RecordEmpty } from '@web/components/RecordEmpty'
import { generateReport, reportListPath, reportRulesPath } from '@web/features/reports/api/requests'
import { ReportActions } from '@web/features/reports/components/ReportActions'
import { ReportObligations } from '@web/features/reports/components/ReportObligations'
import { usePagedResource } from '@web/hooks/usePagedResource'
import { useResource } from '@web/hooks/useResource'
import { useWorkspace } from '@web/lib/workspace'
import { dateLabel, todayIn } from '@web/utils/date'
import { detailState } from '@web/utils/navigation'
import { timezoneLabel } from '@web/utils/timezones'
import { CalendarDays, ChevronRight, FileText, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router'

export function ReportsPage() {
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const kind = params.get('kind') === 'weekly' ? 'weekly' : 'daily'
  const todo = params.get('view') !== 'all'
  const { data, error, refresh, loadMore, loading } = usePagedResource<Report>(
    reportListPath(todo, kind),
    'period',
    2000,
  )
  const rules = useResource<Rules>(reportRulesPath())
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<Error | string>('')
  const [showRules, setShowRules] = useState(false)
  const { notify } = useWorkspace()
  const selectedDate = params.get('date') || todayIn(rules.data?.timezone ?? 'Asia/Shanghai')
  return (
    <div
      className={`${layoutStyles['page']} ${recordLayoutStyles['records-page']}`}
      data-scroll-container
    >
      <div className={`${layoutStyles['page-heading']} ${recordLayoutStyles['slot-page-heading']}`}>
        <div>
          <h2>我的报告</h2>
          <p>把日常的推进，整理成清晰的工作记录。</p>
        </div>
        <button onClick={() => setShowRules(true)}>
          <CalendarDays size={16} />
          汇报安排
        </button>
      </div>
      <div className={recordLayoutStyles['records-surface']}>
        <div className={recordLayoutStyles['records-navigation']}>
          <div
            className={`${layoutStyles['tabs']} ${recordLayoutStyles['slot-tabs']} ${styles['report-view-tabs']}`}
          >
            <button
              aria-pressed={todo}
              data-active={todo}
              onClick={() => setParams({ kind, view: 'todo' })}
            >
              汇报待办
            </button>
            <button
              aria-pressed={!todo}
              data-active={!todo}
              onClick={() => setParams({ kind, view: 'all' })}
            >
              全部报告
            </button>
          </div>
          <div
            className={recordLayoutStyles['report-kind-switch']}
            role="group"
            aria-label="报告类型"
          >
            <button
              data-active={kind === 'daily'}
              aria-pressed={kind === 'daily'}
              onClick={() =>
                setParams({ kind: 'daily', date: selectedDate, view: todo ? 'todo' : 'all' })
              }
            >
              日报
            </button>
            <button
              data-active={kind === 'weekly'}
              aria-pressed={kind === 'weekly'}
              onClick={() =>
                setParams({ kind: 'weekly', date: selectedDate, view: todo ? 'todo' : 'all' })
              }
            >
              周报
            </button>
          </div>
        </div>
        {!todo && (
          <div
            className={`${recordLayoutStyles['records-toolbar']} ${recordLayoutStyles['report-generate']}`}
          >
            <label className={recordLayoutStyles['record-date-field']}>
              <span>报告日期</span>
              <input
                type="date"
                aria-label="报告日期"
                value={selectedDate}
                onClick={(event) => {
                  try {
                    event.currentTarget.showPicker?.()
                  } catch {
                    /* Native picker unavailable. */
                  }
                }}
                onChange={(e) => setParams({ kind, date: e.target.value, view: 'all' })}
              />
            </label>
            <BusyButton
              busy={busy}
              className={controlsStyles['primary']}
              onClick={async () => {
                setBusy(true)
                try {
                  await generateReport({ kind, date: selectedDate }, crypto.randomUUID())
                  refresh()
                  notify('已准备报告，生成状态会自动更新')
                } catch (e) {
                  setFailure(e as Error)
                } finally {
                  setBusy(false)
                }
              }}
            >
              <Sparkles size={16} />
              生成{kind === 'daily' ? '日报' : '周报'}
            </BusyButton>
          </div>
        )}
        <ErrorNotice className={recordLayoutStyles['record-notice']} retry={refresh}>
          {failure || error}
        </ErrorNotice>
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
                          {report.kind === 'weekly' ? '周报' : '日报'} ·{' '}
                          <span className={recordLayoutStyles['record-period']}>
                            {report.period}
                          </span>
                          {report.kind === 'weekly' && (
                            <>
                              {' '}
                              —{' '}
                              <span className={recordLayoutStyles['record-period']}>
                                {report.periodEnd}
                              </span>
                            </>
                          )}
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
              <RecordEmpty
                icon={<FileText size={27} />}
                title={`还没有${kind === 'daily' ? '日报' : '周报'}`}
              >
                选择上方日期生成草稿，整理后即可提交。
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
        <Modal title="我的汇报安排" onClose={() => setShowRules(false)}>
          {rules.data ? (
            <>
              <p>公司时区：{timezoneLabel(rules.data.timezone)}</p>
              {(['daily', 'weekly'] as const).map((k) => (
                <div className={layoutStyles['panel']} key={k}>
                  <h3>{k === 'daily' ? '日报' : '周报'}</h3>
                  <p>
                    {rules.data![k].enabled
                      ? `${rules.data![k].days.map((d) => ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][d]).join('、')} ${rules.data![k].generateTime} 生成，${rules.data![k].deadline} 前提交`
                      : '尚未启用自动生成，可手动准备报告'}
                  </p>
                  {rules.data!.effectivePeriods?.[k] && (
                    <p className={utilitiesStyles['muted']}>
                      当前设置从 {rules.data!.effectivePeriods[k]} 起的周期生效
                    </p>
                  )}
                  {rules.data![k].enabled && (
                    <p className={utilitiesStyles['muted']}>
                      {rules.data![k].reminders === false
                        ? '站内提醒已关闭'
                        : `草稿就绪、截止前 ${rules.data![k].beforeMinutes ?? 30} 分钟及逾期后提醒`}
                    </p>
                  )}
                </div>
              ))}
            </>
          ) : (
            <ErrorNotice>{rules.error || '正在读取…'}</ErrorNotice>
          )}
        </Modal>
      )}
    </div>
  )
}
