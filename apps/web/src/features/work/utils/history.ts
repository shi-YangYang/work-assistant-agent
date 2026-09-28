import type { Progress, Work } from '@paa/api-contracts'

type Revision = NonNullable<Work['history']>[number]
const fields: { key: keyof Progress; label: string }[] = [
  { key: 'title', label: '标题' },
  { key: 'status', label: '状态' },
  { key: 'dueDate', label: '截止日期' },
  { key: 'summary', label: '工作说明' },
  { key: 'blocker', label: '阻碍' },
  { key: 'nextStep', label: '下一步' },
]
const statuses: Record<string, string> = {
  in_progress: '进行中',
  blocked: '有阻碍',
  done: '已完成',
}
const value = (content: Progress, key: keyof Progress) => content[key] ?? ''
const display = (content: Progress, key: keyof Progress) => {
  const text = value(content, key)
  return key === 'status' ? statuses[text] || text : text || '未设置'
}

export function historyChanges(current: Revision, previous?: Revision) {
  // A missing/unauthorized version is not an empty record. Never infer changes
  // across a visibility gap or the history page's oldest boundary.
  const comparable = previous?.revision === current.revision - 1
  return fields
    .filter(({ key }) =>
      comparable
        ? value(current.content, key) !== value(previous.content, key)
        : !!value(current.content, key),
    )
    .map(({ key, label }) => ({
      key,
      label,
      before: comparable ? display(previous.content, key) : undefined,
      after: display(current.content, key),
    }))
}

export function historyOrigin(entry: Revision, workOrigin?: Work['origin']) {
  const verb = entry.revision === 1 ? '创建' : '更新'
  if (
    entry.origin === 'manual' ||
    (!entry.origin && entry.revision === 1 && workOrigin === 'manual')
  )
    return `手动${verb}`
  if (entry.origin === 'assistant_confirmed') return `助手${verb} · 已确认`
  if (entry.origin === 'assistant' || entry.sourceIds.length) return `助手${verb}`
  return '历史记录'
}
