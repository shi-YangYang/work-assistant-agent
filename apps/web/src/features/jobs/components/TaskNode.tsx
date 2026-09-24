import type { TaskNode as Node } from '@paa/api-contracts'
import { Check, Circle, Clock3, LoaderCircle, Minus, ShieldQuestion, X } from 'lucide-react'
import styles from './TaskProgress.module.css'

export function nodeStatus(node: Node, now = Date.now()) {
  if (node.state === 'retry_wait') {
    const seconds = Math.max(0, Math.ceil((Date.parse(node.nextRetryAt || '') - now) / 1000))
    return `${node.kind === 'tool' ? '暂未完成' : '模型暂未响应'}，${Number.isFinite(seconds) && seconds > 0 ? `${seconds} 秒后重试` : '即将重试'} · ${Math.min(3, node.attempts)}/3`
  }
  if (node.state === 'running')
    return node.retries
      ? `正在第 ${node.retries}/3 次重试`
      : node.kind === 'tool'
        ? '执行中'
        : '处理中'
  return {
    waiting: '等待执行',
    succeeded: '已完成',
    failed: '未完成',
    awaiting_confirmation: '待确认',
    awaiting_input: '需要补充',
    cancelled: '已停止',
  }[node.state]
}

export function TaskNode({ node, now }: { node: Node; now: number }) {
  const Icon = {
    waiting: Circle,
    running: LoaderCircle,
    retry_wait: Clock3,
    succeeded: Check,
    failed: X,
    awaiting_confirmation: ShieldQuestion,
    awaiting_input: Circle,
    cancelled: Minus,
  }[node.state]
  return (
    <li className={styles.node} data-state={node.state} data-child={!!node.parentId}>
      <Icon size={14} aria-hidden="true" className={styles.icon} />
      <div className={styles.nodeContent}>
        <span>{node.label}</span>
        <span className={styles.status}>{nodeStatus(node, now)}</span>
        {node.totalRetries > 0 && ['succeeded', 'awaiting_confirmation'].includes(node.state) && (
          <span className={styles.status}>自动重试 {node.totalRetries} 次</span>
        )}
      </div>
    </li>
  )
}
