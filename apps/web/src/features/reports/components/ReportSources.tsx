import utilitiesStyles from '../../../styles/utilities.module.css'
import recordDetailStyles from '../../../components/RecordDetail.module.css'
import styles from './ReportSources.module.css'
import type { Report } from '@paa/api-contracts'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { reportSourcesPath } from '@web/features/reports/api/requests'
import { useResource } from '@web/hooks/useResource'
import { detailState } from '@web/utils/navigation'
import { Link, useLocation } from 'react-router'

export function ReportSources({ report }: { report: Report }) {
  const location = useLocation()
  const { data, error, refresh } = useResource<{
    items: {
      id: string
      workId: string
      title: string
      sourceIds: string[]
      deletedSourceIds?: string[]
      workDeleted?: boolean
      revision: number
    }[]
  }>(reportSourcesPath(report))
  if (error) return <ErrorNotice retry={refresh}>{error}</ErrorNotice>
  return data?.items.length ? (
    <details className={recordDetailStyles['record-evidence']}>
      <summary>工作依据</summary>
      {data.items.map((item) => (
        <div className={styles['source-row']} key={item.id}>
          {item.workDeleted ? (
            <span>{item.title} · 工作已删除</span>
          ) : (
            <Link
              to={`/work/${item.workId}?revision=${item.revision}`}
              state={detailState(location)}
            >
              {item.title} · 第 {item.revision} 版
            </Link>
          )}
          {item.sourceIds.map((id) =>
            item.deletedSourceIds?.includes(id) ? (
              <span key={id} className={utilitiesStyles['muted']}>
                原始消息已删除
              </span>
            ) : (
              <Link key={id} to={`/messages/${id}`} state={detailState(location)}>
                原始上报
              </Link>
            ),
          )}
        </div>
      ))}
    </details>
  ) : null
}
