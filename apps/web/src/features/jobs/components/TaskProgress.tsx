import type { Job } from '@paa/api-contracts'
import { ChevronRight, ListChecks } from 'lucide-react'
import { useEffect, useState } from 'react'
import { TaskNode, nodeStatus } from './TaskNode'
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
  const nodes = (job.nodes ?? []).map((node) =>
    job.state === 'cancelled' && ['waiting', 'running', 'retry_wait'].includes(node.state)
      ? { ...node, state: 'cancelled' as const, nextRetryAt: null }
      : node,
  )
  const [now, setNow] = useState(Date.now)
  const waiting = job.state === 'running' && nodes.some((node) => node.state === 'retry_wait')
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
  const outcome = complete ? job.taskOutcome : null
  const outcomeNames = {
    processing: '正在处理',
    completed: '已完成',
    partial: '部分完成',
    needs_input: '等待补充信息',
    needs_confirmation: '等待你的确认',
    blocked: '暂时无法继续',
    cancelled: '已中断',
  }
  const summary = outcome
    ? `${outcomeNames[outcome.state]}${completed ? ` · ${outcome.state === 'completed' ? '' : '已完成 '}${completed} 个步骤` : ''}${retries ? ` · 自动重试 ${retries} 次` : ''}`
    : complete
      ? `${job.incompleteTask ? '仍有事项未完成 · ' : job.state === 'awaiting_input' && nodes.some((node) => node.state === 'awaiting_input') ? '等待补充信息 · ' : ''}已完成 ${completed} 个步骤${confirmations ? ` · ${confirmations} 项待确认` : ''}${retries ? ` · 自动重试 ${retries} 次` : ''}`
      : job.state === 'queued'
        ? '等待继续处理'
        : job.state === 'cancelled'
          ? '已中断'
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
          <button type="button" disabled={busy || disabled} onClick={onRetry}>
            {busy ? '正在重试…' : '重试'}
          </button>
        </div>
      </div>
    )
  return (
    <div className={styles.progress}>
      <details
        className={styles.details}
        open={expanded}
        onToggle={(event) => onExpandedChange?.(event.currentTarget.open)}
        data-running={job.state === 'running' && current?.state === 'running'}
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
          {nodes.map((node) => (
            <TaskNode
              key={node.id}
              node={node}
              now={now}
              running={
                job.state === 'running' && node.id === current?.id && node.state === 'running'
              }
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
