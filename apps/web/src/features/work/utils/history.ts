import type { Progress, Work, WorkDocument, WorkNode } from '@paa/api-contracts'
import { documentFromText, documentMaterialIds, splitDocumentMaterials } from './document'

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

function bodyContent(body: WorkDocument) {
  const normalize = (node: WorkNode): WorkNode => ({
    type: node.type,
    text: node.text,
    attrs: Object.fromEntries(
      Object.entries(node.attrs ?? {})
        .filter(([key, value]) => key !== 'id' && value !== null)
        .sort(([left], [right]) => left.localeCompare(right)),
    ),
    marks: node.marks ?? [],
    content: (node.content ?? []).map(normalize),
  })
  const nodes = splitDocumentMaterials(body).body.content.map(normalize)
  // Tiptap adds an empty cursor paragraph after a material; it is not a content edit.
  while (nodes.at(-1)?.type === 'paragraph' && !nodes.at(-1)?.content?.length) nodes.pop()
  return nodes
}

const sortedIds = (ids: string[]) => [...new Set(ids)].sort()

export function historyChanges(current: Revision, previous?: Revision) {
  // A missing/unauthorized version is not an empty record. Never infer changes
  // across a visibility gap or the history page's oldest boundary.
  const comparable = previous?.revision === current.revision - 1
  const changes: { key: string; label: string; before: string | undefined; after: string }[] =
    fields
      .filter(({ key }) => key !== 'summary' || !current.content.body)
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
  const body = bodyContent(current.content.body ?? documentFromText(current.content.summary))
  const previousBody = previous
    ? bodyContent(previous.content.body ?? documentFromText(previous.content.summary))
    : []
  if (
    current.content.body &&
    (comparable ? JSON.stringify(body) !== JSON.stringify(previousBody) : body.length > 0)
  ) {
    changes.push({
      key: 'body',
      label: '工作内容',
      before: comparable ? previous.content.bodyText || '空正文' : undefined,
      after: current.content.bodyText || (body.length ? '正文格式已更新' : '空正文'),
    })
  }
  const references = sortedIds(documentMaterialIds(current.content.body))
  const previousReferences = sortedIds(documentMaterialIds(previous?.content.body))
  const materials = sortedIds(current.content.materialIds ?? [])
  const previousMaterials = sortedIds(previous?.content.materialIds ?? [])
  const referencesChanged = comparable
    ? JSON.stringify(references) !== JSON.stringify(previousReferences)
    : references.length > 0
  const materialsChanged = comparable
    ? JSON.stringify(materials) !== JSON.stringify(previousMaterials)
    : materials.length > 0
  if (referencesChanged || materialsChanged) {
    changes.push({
      key: 'materials',
      label: '材料',
      before: comparable
        ? `${(referencesChanged ? previousReferences : previousMaterials).length} 个`
        : undefined,
      after: `${(referencesChanged ? references : materials).length} 个`,
    })
  }
  if (current.content._changeKind?.startsWith('update_'))
    changes.push({
      key: 'update',
      label: current.content._updateDeleted
        ? '删除进展'
        : current.content._changeKind === 'update_edit'
          ? '更正进展'
          : '记录进展',
      before: undefined,
      after: current.content._updateText || '附件进展',
    })
  return changes
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
