import type { WorkDocument, WorkNode } from '@paa/api-contracts'

export const emptyDocument = (): WorkDocument => ({ schemaVersion: 1, content: [] })
export function documentText(body?: WorkDocument) {
  const text = (node: WorkNode): string => {
    const value =
      (node.text ?? '') +
      (node.type === 'hardBreak' ? '\n' : '') +
      (node.content ?? [])
        .map(text)
        .join(
          ['taskList', 'bulletList', 'orderedList', 'taskItem', 'listItem', 'blockquote'].includes(
            node.type,
          )
            ? '\n'
            : '',
        )
    return node.type === 'taskItem' ? `${node.attrs?.checked ? '☑' : '☐'} ${value}` : value
  }
  return body?.content.map(text).join('\n') ?? ''
}

export function documentChecklist(body?: WorkDocument) {
  const result = new Map<string, { text: string; checked: boolean }>()
  const walk = (node: WorkNode) => {
    if (node.type === 'taskItem' && typeof node.attrs?.id === 'string')
      result.set(node.attrs.id, {
        text: documentText({ schemaVersion: 1, content: node.content ?? [] }),
        checked: node.attrs.checked === true,
      })
    node.content?.forEach(walk)
  }
  body?.content.forEach(walk)
  return result
}

export function documentMaterialIds(body?: WorkDocument): string[] {
  const ids = (node: WorkNode): string[] =>
    node.type === 'material'
      ? [String(node.attrs?.materialId ?? '')]
      : (node.content ?? []).flatMap(ids)
  return [...new Set(body?.content.flatMap(ids) ?? [])]
}
export function documentFromText(text: string): WorkDocument {
  return {
    schemaVersion: 1,
    content: text
      ? text.split('\n').map((line) => ({
          type: 'paragraph',
          ...(line ? { content: [{ type: 'text', text: line }] } : {}),
        }))
      : [],
  }
}

export function removeDocumentMaterial(body: WorkDocument, id: string): WorkDocument {
  const remove = (nodes: WorkNode[]): WorkNode[] =>
    nodes.flatMap((node) => {
      if (node.type === 'material' && node.attrs?.materialId === id) return []
      return [{ ...node, ...(node.content ? { content: remove(node.content) } : {}) }]
    })
  return { ...body, content: remove(body.content) }
}

export function splitDocumentMaterials(body: WorkDocument) {
  const materials: WorkNode[] = []
  const text = (nodes: WorkNode[]): WorkNode[] =>
    nodes.flatMap((node) => {
      if (node.type === 'material') {
        materials.push(node)
        return []
      }
      return [{ ...node, ...(node.content ? { content: text(node.content) } : {}) }]
    })
  return { body: { ...body, content: text(body.content) }, materials }
}
