import type { WorkDocument, WorkNode } from '@paa/api-contracts'

function blockText(node: WorkNode): string {
  if (node.type === 'material') return '〔已选材料〕'
  if (node.type === 'hardBreak') return '\n'
  const text =
    node.text ??
    (node.content ?? [])
      .map(blockText)
      .join(['bulletList', 'orderedList', 'taskList'].includes(node.type) ? '\n' : '')
  if (node.type === 'taskItem') return `${node.attrs?.checked ? '☑' : '☐'} ${text}`
  if (node.type === 'listItem') return `• ${text}`
  return text
}
export function workChangeText(
  key: string,
  value: unknown,
  names: Record<string, string> = {},
): string | undefined {
  if (key === 'body' && value && typeof value === 'object')
    return (value as WorkDocument).content?.map(blockText).join('\n') || '清空正文'
  if (key === 'bodyEdits' && Array.isArray(value))
    return value
      .map((edit, index) => {
        if (edit.action === 'set_checked')
          return `${index + 1}. ${edit.text || '清单事项'}：${edit.beforeChecked ? '已完成' : '未完成'} → ${edit.checked ? '已完成' : '未完成'}`
        const append = ['append', 'append_checklist'].includes(edit.action)
        const label =
          (
            {
              append: '追加内容',
              replace: '修改指定内容',
              remove: '删除指定内容',
              append_checklist: '追加清单',
              replace_checklist: '整理为清单',
            } as Record<string, string>
          )[edit.action] ?? '修改内容'
        const before = edit.before?.map(blockText).join('\n')
        const after = edit.blocks?.map(blockText).join('\n')
        return [
          `${index + 1}. ${label}`,
          !append ? `原内容：\n${before || '（空内容）'}` : '',
          edit.action === 'remove'
            ? '修改为：删除以上内容'
            : `${append ? '新增内容' : '修改为'}：\n${after || '（空内容）'}`,
        ]
          .filter(Boolean)
          .join('\n')
      })
      .join('\n\n')
  if (key === 'update' && value && typeof value === 'object') {
    const update = value as {
      action: string
      text?: string
      before?: string
      materialIds?: unknown[]
      materials?: unknown[]
    }
    return [
      (
        { create: '记录新进展', edit: '更正进展', delete: '删除这条进展' } as Record<string, string>
      )[update.action],
      update.before !== undefined ? `原进展：${update.before || '附件进展'}` : '',
      update.action !== 'delete' ? update.text || '附件进展' : '',
      update.materials?.length || update.materialIds?.length
        ? `关联 ${(update.materials?.length ?? 0) + (update.materialIds?.length ?? 0)} 个材料`
        : '',
    ]
      .filter(Boolean)
      .join('\n')
  }
  if (key === 'materials' && Array.isArray(value))
    return (
      value
        .map((item) => names[item.attachmentId ?? item.fileId] || item.name || '已选文件')
        .join('、') || '无新材料'
    )
  if (key === 'materialIds' && Array.isArray(value))
    return value.length
      ? value.map((id) => names[String(id)] || '已保存材料').join('、')
      : '移除所有材料'
  if (key === 'removeMaterial' && value && typeof value === 'object')
    return `移除${'id' in value && names[String(value.id)] ? `「${names[String(value.id)]}」` : '指定材料'}，历史引用保留`
  return undefined
}
