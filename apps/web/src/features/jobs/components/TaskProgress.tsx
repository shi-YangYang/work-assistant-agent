import type { Job } from '@paa/api-contracts'
import { ChevronRight, ListChecks } from 'lucide-react'
import { useEffect, useState } from 'react'
import { TaskNode, nodeStatus } from './TaskNode'
import styles from './TaskProgress.module.css'

export function TaskProgress({
  job,
  busy,
  onRetry,
}: {
  job: Job
  busy: boolean
  onRetry: () => void
}) {
  const nodes = job.nodes ?? []
  const [now, setNow] = useState(Date.now)
  const waiting = nodes.some((node) => node.state === 'retry_wait')
  useEffect(() => {
    if (!waiting) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [waiting])
  const current = [...nodes]
    .reverse()
    .find((node) => ['running', 'retry_wait'].includes(node.state))
  const failed = [...nodes].reverse().find((node) => node.canRetry)
  const complete = !['running', 'queued', 'failed', 'awaiting_retry', 'cancelled'].includes(
    job.state,
  )
  const completed = nodes.filter((node) => node.state === 'succeeded').length
  const confirmations = nodes.filter((node) => node.state === 'awaiting_confirmation').length
  const retries = nodes.reduce((total, node) => total + node.totalRetries, 0)
  const summary = complete
    ? `已完成 ${completed} 个步骤${confirmations ? ` · ${confirmations} 项待确认` : ''}${retries ? ` · 自动重试 ${retries} 次` : ''}`
    : job.state === 'queued'
      ? '等待继续处理'
      : job.state === 'cancelled'
        ? '处理已停止'
        : current
          ? `${current.label} · ${nodeStatus(current, now)}`
          : failed
            ? `${failed.label} · 未完成`
            : '处理步骤'
  if (['failed', 'awaiting_retry'].includes(job.state))
    return (
      <div className={`${styles.progress} ${styles.failure}`} role="status">
        <p>{job.error || failed?.error || '本次处理未完成，请重试。'}</p>
        <div className={styles.actions}>
          <button type="button" disabled={busy} onClick={onRetry}>
            {busy ? '正在重试…' : '重试'}
          </button>
        </div>
      </div>
    )
  return (
    <div className={styles.progress}>
      <details className={styles.details}>
        <summary>
          <ListChecks size={15} aria-hidden="true" />
          <span>{summary}</span>
          <ChevronRight size={14} aria-hidden="true" className={styles.chevron} />
        </summary>
        <ol className={styles.nodes} aria-label="处理步骤">
          {nodes.map((node) => (
            <TaskNode key={node.id} node={node} now={now} />
          ))}
        </ol>
      </details>
    </div>
  )
}
