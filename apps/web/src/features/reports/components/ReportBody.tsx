import utilitiesStyles from '../../../styles/utilities.module.css'
import styles from './ReportBody.module.css'
import type { ReportContent } from '@paa/api-contracts'

export const reportLabels: Record<keyof ReportContent, string> = {
  completed: '完成的工作',
  ongoing: '进行中的工作',
  blockers: '问题与阻碍',
  next: '下一步计划',
}

export function reportHasContent(content: ReportContent) {
  return Object.values(content).some((text) => text.trim())
}

export function ReportBody({
  content,
  compact = false,
}: {
  content: ReportContent
  compact?: boolean
}) {
  return (
    <div className={styles['report-body']} data-compact={compact}>
      {Object.entries(reportLabels).map(([key, label]) => (
        <section key={key}>
          <h3>{label}</h3>
          <p className={utilitiesStyles['preserve']}>
            {content[key as keyof ReportContent] || '暂无记录'}
          </p>
        </section>
      ))}
    </div>
  )
}
