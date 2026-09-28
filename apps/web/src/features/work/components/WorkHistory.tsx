import type { Work } from '@paa/api-contracts'
import { Link, useLocation } from 'react-router'
import { dateLabel } from '@web/utils/date'
import { detailState } from '@web/utils/navigation'
import { historyChanges, historyOrigin } from '../utils/history'
import styles from './WorkDetail.module.css'

export function WorkHistory({ work }: { work: Work }) {
  const location = useLocation()
  const history = work.history ?? []
  return (
    <div className={styles.timeline}>
      {history.map((entry, index) => {
        const changes = historyChanges(entry, history[index + 1])
        return (
          <article key={entry.id}>
            <small>
              {historyOrigin(entry, work.origin)} · {dateLabel(entry.createdAt)} · 第{' '}
              {entry.revision} 版
            </small>
            <dl className={styles.changes}>
              {changes.map((change) => (
                <div key={change.key}>
                  <dt>{change.label}</dt>
                  <dd>
                    {change.before !== undefined && (
                      <>
                        <span className={styles.before}>{change.before}</span>
                        <span className={styles.arrow} aria-label="改为">
                          →
                        </span>
                      </>
                    )}
                    <span>{change.after}</span>
                  </dd>
                </div>
              ))}
            </dl>
            {!changes.length && <p>工作字段未变化</p>}
            {entry.sourceIds.map((source) =>
              entry.deletedSourceIds?.includes(source) ? (
                <small key={source}>原始消息已删除</small>
              ) : (
                <Link key={source} to={`/messages/${source}`} state={detailState(location)}>
                  查看原始上报
                </Link>
              ),
            )}
          </article>
        )
      })}
    </div>
  )
}
