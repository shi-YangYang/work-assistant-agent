import { useCallback, useEffect, useId, useRef, useState } from 'react'
import type { UsageRecord } from '@paa/api-contracts'
import { Empty } from '@web/components/feedback/Empty'
import { dateLabel } from '@web/utils/date'
import { purposeNames, stateNames, duration, number } from './usage-display'
import styles from './ModelUsagePage.module.css'

export function UsageTable({ items }: { items: UsageRecord[] }) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const hintId = useId()
  const [edges, setEdges] = useState({ left: false, right: false })
  const measure = useCallback(() => {
    const node = scrollRef.current
    if (!node) return
    const left = node.scrollLeft > 1
    const right = node.scrollWidth - node.clientWidth - node.scrollLeft > 1
    setEdges((previous) =>
      previous.left === left && previous.right === right ? previous : { left, right },
    )
  }, [])
  useEffect(() => {
    const node = scrollRef.current
    if (!node) return
    const frame = requestAnimationFrame(measure)
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure)
    observer?.observe(node)
    window.addEventListener('resize', measure)
    return () => {
      cancelAnimationFrame(frame)
      observer?.disconnect()
      window.removeEventListener('resize', measure)
    }
  }, [measure, items])
  return items.length ? (
    <div className={styles['usage-table-section']}>
      {edges.left || edges.right ? (
        <p className={styles['scroll-hint']} id={hintId} role="status">
          {edges.left && edges.right
            ? '左右滑动查看全部列'
            : edges.right
              ? '向右滑动查看更多列'
              : '向左滑动查看前面的列'}
        </p>
      ) : null}
      <div
        ref={scrollRef}
        className={styles['usage-table-wrap']}
        role="region"
        aria-label="模型调用记录"
        aria-describedby={edges.left || edges.right ? hintId : undefined}
        tabIndex={0}
        onScroll={measure}
        data-scroll-left={edges.left}
        data-scroll-right={edges.right}
      >
        <table className={styles['usage-table']}>
          <thead>
            <tr>
              <th>时间</th>
              <th>服务 / 模型</th>
              <th>用途</th>
              <th>结果</th>
              <th>耗时</th>
              <th>输入 / 输出 Token</th>
            </tr>
          </thead>
          <tbody>
            {items.map((row) => (
              <tr key={row.id}>
                <td>
                  <time
                    dateTime={row.createdAt}
                    title={new Date(row.createdAt).toLocaleString('zh-CN')}
                    aria-label={new Date(row.createdAt).toLocaleString('zh-CN')}
                  >
                    {dateLabel(row.createdAt)}
                  </time>
                </td>
                <td>
                  <span>
                    {row.service || (row.purpose === 'admin_test' ? '未保存配置' : '历史未知')}
                  </span>
                  <small>{row.model || '历史未知'}</small>
                </td>
                <td>{purposeNames[row.purpose] || '历史未知'}</td>
                <td>
                  <span className={styles['usage-state']} data-status={row.state}>
                    {stateNames[row.state] || '未知'}
                  </span>
                  {row.error && <small>{row.error}</small>}
                </td>
                <td>{duration(row.elapsedMs)}</td>
                <td>
                  {number(row.inputTokens)} / {number(row.outputTokens)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  ) : (
    <Empty title="本期没有符合条件的调用" />
  )
}
