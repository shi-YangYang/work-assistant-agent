import { useAttachmentUploads } from '../../../../apps/web/src/features/assistant/hooks/composer/useAttachmentUploads'
import { identityScope } from '../../../../apps/web/src/lib/session-drafts'
import { useWorkspace } from '../../../../apps/web/src/lib/workspace'

export function TestAttachmentUploads() {
  const { identity, drafts, setDraft } = useWorkspace()
  useAttachmentUploads(identityScope(identity), drafts, setDraft)
  return null
}
