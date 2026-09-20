import { Assistant } from '@web/features/assistant/components/Conversations'
import { useParams } from 'react-router'

export function AssistantPage() {
  const { conversationId } = useParams()
  return <Assistant conversationId={conversationId} />
}
