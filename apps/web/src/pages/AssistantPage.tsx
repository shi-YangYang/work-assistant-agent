import { Assistant } from '@web/features/assistant/components/Conversations'
import { ErrorDiagnostics } from '@web/lib/support-link'
import { useParams } from 'react-router'

export function AssistantPage() {
  const { conversationId } = useParams()
  return (
    <ErrorDiagnostics.Provider value={true}>
      <Assistant conversationId={conversationId} />
    </ErrorDiagnostics.Provider>
  )
}
