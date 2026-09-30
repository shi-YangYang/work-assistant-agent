import type { Job } from '@paa/api-contracts'
import { ChevronRight, ListChecks } from 'lucide-react'
import { useEffect, useState } from 'react'
import { TaskNode, nodeStatus } from './TaskNode'
import { completionSummary, nodeName, progressView } from '../utils/progress'
import styles from './TaskProgress.module.css'

export function TaskProgress({
  job,
  busy,
  onRetry,
  disabled = false,
  expanded,
  onExpandedChange,
}: {
  job: Job
  busy: boolean
  disabled?: boolean
  onRetry: () => void
  expanded?: boolean
  onExpandedChange?: (expanded: boolean) => void
}) {
  const { nodes, rows, active, current, parallel, completed, retries } = progressView(job)
  const [now, setNow] = useState(Date.now)
  const waiting = job.state === 'running' && nodes.some((node) => node.state === 'retry_wait')
  useEffect(() => {
    if (!waiting) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [waiting])
  const failed = [...nodes].reverse().find((node) => node.canRetry)
  const complete = ['succeeded', 'awaiting_input'].includes(job.state)
  const outcome = complete ? job.taskOutcome : null
  const summary = complete
    ? completionSummary(job, completed, retries)
    : job.state === 'queued'
      ? '等待继续处理'
      : job.state === 'cancelled'
        ? `已中断${completed ? ` · 已完成 ${completed} 项操作` : ''}`
        : parallel
          ? '多项操作处理中'
          : current
            ? `${nodeName(current)} · ${nodeStatus(current, now)}`
            : '处理请求'
  const running = job.state === 'running' && active.some((node) => node.state === 'running')
  if (['failed', 'awaiting_retry'].includes(job.state))
    return (
      <div className={`${styles.progress} ${styles.failure}`} role="status">
        <p>{job.error || failed?.error || '本次处理未完成，请重试。'}</p>
        <div className={styles.actions}>
          <button type="button" disabled={busy || disabled} onClick={onRetry}>
            {busy ? '正在重试…' : '重试'}
          </button>
        </div>
      </div>
    )
  if (!rows.length) {
    if (complete && (!outcome || outcome.state === 'completed') && !job.incompleteTask && !retries)
      return null
    return (
      <div className={`${styles.progress} ${styles.activity}`} data-running={running} role="status">
        <span>{summary}</span>
      </div>
    )
  }
  return (
    <div className={styles.progress}>
      <details
        className={styles.details}
        open={expanded}
        onToggle={(event) => onExpandedChange?.(event.currentTarget.open)}
        data-running={running}
      >
        <summary
          onClick={(event) => {
            if (!onExpandedChange) return
            event.preventDefault()
            onExpandedChange(!expanded)
          }}
        >
          <ListChecks size={15} aria-hidden="true" />
          <span>{summary}</span>
          <ChevronRight size={14} aria-hidden="true" className={styles.chevron} />
        </summary>
        <ol className={styles.nodes} aria-label="处理步骤">
          {rows.map((node) => (
            <TaskNode
              key={node.id}
              node={node}
              now={now}
              running={job.state === 'running' && node.state === 'running'}
            />
          ))}
        </ol>
      </details>
      {outcome &&
        ['partial', 'needs_input', 'blocked'].includes(outcome.state) &&
        (outcome.reason || outcome.remaining[0]) && (
          <p className={styles.outcome} role="status">
            {outcome.reason || outcome.remaining[0]}
          </p>
        )}
    </div>
  )
}
