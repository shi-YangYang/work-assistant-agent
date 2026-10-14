import type { Job } from '@paa/api-contracts'
import { ChevronRight, ListChecks, LoaderCircle } from 'lucide-react'
import { TaskNode, nodeStatus } from './TaskNode'
import { completionSummary, nodeName, progressView } from '../utils/progress'
import { useProgressClock } from './useProgressClock'
import styles from './TaskProgress.module.css'

export function TaskProgress({
  job,
  busy,
  onRetry,
  disabled = false,
  expanded,
  onExpandedChange,
  replyActivity,
}: {
  job: Job
  busy: boolean
  disabled?: boolean
  onRetry: () => void
  expanded?: boolean
  onExpandedChange?: (expanded: boolean) => void
  replyActivity?: string
}) {
  const { nodes, rows: visibleRows, active, completed, retries } = progressView(job)
  const rows = visibleRows.filter((node) => node.kind !== 'model' || node.state !== 'running')
  const waiting = job.state === 'running' && nodes.some((node) => node.state === 'retry_wait')
  const retrying = active.length > 0 && active.every((node) => node.state === 'retry_wait')
  const attention = !active.length
    ? [...nodes]
        .reverse()
        .find((node) => ['awaiting_input', 'awaiting_confirmation'].includes(node.state))
    : undefined
  const reply = ['running', 'succeeded', 'awaiting_input'].includes(job.state) && !!replyActivity
  const generatingImages =
    job.state === 'running' &&
    active.some(
      (node) => node.kind === 'tool' && node.label === '生成图片' && node.state === 'running',
    )
  const images = job.imageGeneration ?? []
  const imageSummary = `正在生成图片${images.length ? ` · 已完成 ${images.filter((slot) => slot.state === 'ready').length}/${images.length} 张` : ''}`
  // Keep transport/model phases in one visible activity. Delivery is part of
  // generating the reply, so it does not introduce a brief third label.
  const activity = generatingImages
    ? undefined
    : reply
      ? '生成回答'
      : job.state === 'running' && !retrying && !attention
        ? '思考中'
        : undefined
  const { now, seconds } = useProgressClock(
    `${job.id}:${job.attempt}:${job.fence}`,
    job.state === 'running' && (!!activity || waiting),
    active.find((node) => node.kind === 'model')?.activity?.startedAt,
  )
  const failed = [...nodes].reverse().find((node) => node.canRetry)
  const complete = ['succeeded', 'awaiting_input'].includes(job.state)
  const outcome = complete ? job.taskOutcome : null
  const retryCount = active.reduce((count, node) => Math.max(count, node.retries), 0)
  const activityStatus = `${activity === '思考中' ? `${seconds} 秒` : '处理中'}${retryCount ? ` · 第 ${retryCount}/3 次重试` : ''}`
  const summary = generatingImages
    ? imageSummary
    : activity
      ? `${activity} · ${activityStatus}`
      : complete
        ? completionSummary(job, completed, retries)
        : job.state === 'queued'
          ? '等待继续处理'
          : job.state === 'cancelled'
            ? `已中断${completed ? ` · 已完成 ${completed} 项操作` : ''}`
            : retrying
              ? active.length === 1
                ? nodeStatus(active[0], now)
                : '多项操作重试中'
              : attention
                ? `${nodeName(attention)} · ${nodeStatus(attention, now)}`
                : '处理请求'
  const running =
    !!activity || (job.state === 'running' && active.some((node) => node.state === 'running'))
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
    if (
      !activity &&
      complete &&
      (!outcome || outcome.state === 'completed') &&
      !job.incompleteTask &&
      !retries
    )
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
          {activity && (
            <li className={styles.node} data-reply-activity data-running="true">
              <LoaderCircle size={14} aria-hidden="true" className={styles.icon} />
              <div className={styles.nodeContent}>
                <span className={styles.name}>{activity}</span>
                <span className={styles.status}>{activityStatus}</span>
              </div>
            </li>
          )}
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
