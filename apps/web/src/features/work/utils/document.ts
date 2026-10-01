import type { WorkDocument, WorkNode } from '@paa/api-contracts'

export const emptyDocument = (): WorkDocument => ({ schemaVersion: 1, content: [] })
export function documentText(body?: WorkDocument) {
  const text = (node: WorkNode): string =>
    (node.text ?? '') +
    (node.type === 'hardBreak' ? '\n' : '') +
    (node.content ?? []).map(text).join('')
  return body?.content.map(text).join('\n') ?? ''
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
