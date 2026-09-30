import type { Job, TaskNode } from '@paa/api-contracts'

const internalLabels = new Set(['读取操作结果', '读取执行记录', '等待用户回答', '整理答复'])
const activeStates = new Set(['running', 'retry_wait'])
const pendingStates = new Set(['waiting', 'running', 'retry_wait'])
const attentionStates = new Set(['failed', 'cancelled', 'awaiting_input', 'awaiting_confirmation'])

export function isOperation(node: TaskNode) {
  return node.presentation
    ? node.presentation.type === 'operation'
    : node.kind === 'tool' && !internalLabels.has(node.label)
}

export function nodeName(node: TaskNode) {
  const label = node.kind === 'model' && node.label === '思考中' ? '处理请求' : node.label
  return node.presentation?.subject ? `${label}：${node.presentation.subject}` : label
}

export function progressView(job: Job) {
  const live = job.state === 'running' || job.state === 'queued'
  const nodes = (job.nodes ?? []).map((node) => {
    if (!live && pendingStates.has(node.state))
      return {
        ...node,
        state: job.state === 'cancelled' ? ('cancelled' as const) : ('failed' as const),
        nextRetryAt: null,
      }
    return node
  })
  const active = live ? nodes.filter((node) => activeStates.has(node.state)) : []
  const visible = nodes.filter(
    (node) =>
      isOperation(node) ||
      node.kind === 'compaction' ||
      attentionStates.has(node.state) ||
      node.state === 'retry_wait' ||
      node.totalRetries > 0,
  )
  // A hidden parent must not leave a misleading indentation in the flat projection.
  const visibleIds = new Set(visible.map((node) => node.id))
  const rows = visible.map((node) =>
    node.parentId && !visibleIds.has(node.parentId) ? { ...node, parentId: null } : node,
  )
  const leafActive = active.filter((node) => !active.some((other) => other.parentId === node.id))
  const current = leafActive.length === 1 ? leafActive[0] : undefined
  const completed = nodes.filter((node) => isOperation(node) && node.state === 'succeeded').length
  // Counts are per node, not parent subtree totals; use every raw node exactly once.
  const retries = [...new Map(nodes.map((node) => [node.id, node])).values()].reduce(
    (sum, node) => sum + node.totalRetries,
    0,
  )
  return { nodes, rows, active, current, completed, retries, parallel: leafActive.length > 1 }
}

export function completionSummary(job: Job, completed: number, retries: number) {
  const names = {
    processing: '正在处理',
    completed: '已完成',
    partial: '部分完成',
    needs_input: '等待补充信息',
    needs_confirmation: '等待你的确认',
    blocked: '暂时无法继续',
    cancelled: '已中断',
  }
  const waiting = job.nodes?.some((node) => node.state === 'awaiting_input')
  const confirming = job.nodes?.some((node) => node.state === 'awaiting_confirmation')
  const status = job.taskOutcome
    ? names[job.taskOutcome.state]
    : job.incompleteTask
      ? '仍有事项未完成'
      : job.state === 'awaiting_input'
        ? confirming
          ? '等待你的确认'
          : waiting
            ? '等待补充信息'
            : '仍有事项未完成'
        : '已完成'
  return `${status}${completed ? ` · ${status === '已完成' ? '' : '已完成 '}${completed} 项操作` : ''}${retries ? ` · 自动重试 ${retries} 次` : ''}`
}
