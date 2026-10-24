import type { Work } from '@paa/api-contracts'
import { useState } from 'react'
import { Link, useLocation } from 'react-router'
import { dateLabel } from '@web/utils/date'
import { detailState } from '@web/utils/navigation'
import { historyChanges, historyOrigin } from '../../utils/history'
import styles from './WorkDetail.module.css'

export function WorkHistory({ work }: { work: Work }) {
  const location = useLocation()
  const [expanded, setExpanded] = useState(false)
  const history = (work.history ?? []).filter((entry) => entry.revision <= work.revision)
  if (!history.some((entry) => entry.revision > 1)) return null
  return (
    <section className={styles.history} aria-label="修改记录">
      <h3>修改记录</h3>
      <div className={styles.timeline}>
        {(expanded ? history : history.slice(0, 3)).map((entry, index) => {
          const changes = historyChanges(entry, history[index + 1])
          return (
            <article key={entry.id}>
              <div className={styles['history-meta']}>
                <small>
                  {historyOrigin(entry, work.origin)} · {dateLabel(entry.createdAt)}
                </small>
                <Link
                  to={`/work/${work.id}?revision=${entry.revision}`}
                  state={detailState(location)}
                >
                  查看当时内容
                </Link>
              </div>
              {!!changes.length && (
                <details className={styles['history-change']}>
                  <summary>
                    {entry.revision === 1
                      ? '创建工作'
                      : changes
                          .map((change) =>
                            change.key === 'body'
                              ? change.after
                              : change.key === 'update'
                                ? change.label
                                : change.key.startsWith('check:')
                                  ? `${change.after === '已完成' ? '勾选' : '取消勾选'}：${change.label}`
                                  : change.key === 'status'
                                    ? `状态：${change.before} → ${change.after}`
                                    : `修改${change.label}`,
                          )
                          .join('、')}
                  </summary>
                  <dl className={styles.changes}>
                    {changes.map((change) => (
                      <div
                        key={change.key}
                        className={
                          change.key.startsWith('check:') ? styles['check-change'] : undefined
                        }
                      >
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
                </details>
              )}
              {!changes.length && (
                <p>
                  {history[index + 1]?.revision === entry.revision - 1
                    ? '工作内容未变化'
                    : '较早内容不可比较，查看当时内容了解详情'}
                </p>
              )}
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
        {history.length > 3 && (
          <button className={styles['history-more']} onClick={() => setExpanded(!expanded)}>
            {expanded ? '收起较早记录' : `查看更早的 ${history.length - 3} 条修改`}
          </button>
        )}
      </div>
    </section>
  )
}
