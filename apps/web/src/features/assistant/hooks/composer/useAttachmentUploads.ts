import { useEffect } from 'react'
import type { DraftStore, WorkspaceState } from '@web/lib/workspace'
import { attachmentUploads } from '../../lib/attachment-uploads'

// Mounted with the signed-in shell, so navigating away does not orphan uploads.
export function useAttachmentUploads(
  scope: string,
  drafts: DraftStore,
  setDraft: WorkspaceState['setDraft'],
) {
  useEffect(() => {
    attachmentUploads.bind(scope, setDraft)
    return () => attachmentUploads.pause()
  }, [scope, setDraft])
  useEffect(() => attachmentUploads.sync(drafts), [scope, drafts, setDraft])
}
