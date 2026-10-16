import type { Report } from '@paa/api-contracts'
import { PageHeader } from '@web/components/layout/page-header/PageHeader'
import { timezoneLabel } from '@web/utils/timezones'
import type { ReactNode } from 'react'
import styles from './ReportDetail.module.css'

export function ReportHeader({
  report,
  compact,
  actions,
}: {
  report: Report
  compact: boolean
  actions?: ReactNode
}) {
  const start = report.period.replaceAll('-', '/')
  const end = report.periodEnd.replaceAll('-', '/')
  const period =
    report.kind === 'weekly'
      ? `${start} — ${start.slice(0, 4) === end.slice(0, 4) ? end.slice(5) : end}`
      : start
  const timezone = timezoneLabel(report.timezone)
  return (
    <PageHeader
      className={styles.header}
      context={compact ? 'embedded' : 'detail'}
      title={report.kind === 'weekly' ? '周报' : '日报'}
      meta={
        <span className={styles.status}>
          {report.publishedRevision
            ? `已提交第 ${report.historical ? report.revision : report.publishedRevision} 版`
            : '草稿'}
        </span>
      }
      description={
        <>
          <p className={styles.period}>{period}</p>
          <p className={styles.metadata}>
            {report.ownerName && <span>{report.ownerName}</span>}
            <span title={timezone}>{timezone.split('（')[0]}</span>
          </p>
        </>
      }
      actions={actions}
    />
  )
}
