import { Node, mergeAttributes } from '@tiptap/core'
import { NodeViewWrapper, ReactNodeViewRenderer, type NodeViewProps } from '@tiptap/react'
import type { Attachment, Work, WorkMaterial } from '@paa/api-contracts'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { useResource } from '@web/hooks/useResource'
import { createContext, useContext } from 'react'
import { MaterialView } from '../materials/MaterialView'

export const MaterialContext = createContext<{ work?: Work; pending: Attachment[]; own: boolean }>({
  pending: [],
  own: false,
})
function MaterialNodeView({ node }: NodeViewProps) {
  const { work, pending, own } = useContext(MaterialContext)
  return (
    <NodeViewWrapper contentEditable={false} data-material-id={String(node.attrs.materialId)}>
      <WorkMaterialDisplay
        id={String(node.attrs.materialId)}
        work={work}
        pending={pending}
        own={own}
      />
    </NodeViewWrapper>
  )
}
export function WorkMaterialDisplay({
  id,
  work,
  pending = [],
  own = false,
}: {
  id: string
  work?: Work
  pending?: Attachment[]
  own?: boolean
}) {
  const uploaded = pending.find((file) => file.id === id)
  const { data, error, refresh } = useResource<WorkMaterial>(
    !uploaded && work
      ? `/work-items/${work.id}/materials/${id}${work.historical ? `?revision=${work.revision}` : ''}`
      : null,
  )
  const attachment = uploaded ?? data?.attachment
  return (
    <div>
      <ErrorNotice retry={refresh}>{error}</ErrorNotice>
      {attachment ? (
        <MaterialView attachment={attachment} own={own && !uploaded} refresh={refresh} />
      ) : (
        !error && <small>正在读取材料…</small>
      )}
    </div>
  )
}
export const WorkMaterialNode = Node.create({
  name: 'material',
  group: 'block',
  atom: true,
  draggable: true,
  addAttributes: () => ({ materialId: { default: null } }),
  parseHTML: () => [{ tag: 'div[data-work-material]' }],
  renderHTML: ({ HTMLAttributes }) => [
    'div',
    mergeAttributes(HTMLAttributes, { 'data-work-material': '' }),
  ],
  addNodeView: () => ReactNodeViewRenderer(MaterialNodeView),
})
