import type { DraftLifecycle } from '@web/lib/session-drafts'
import type { Composer } from './audio-capture'
import { attachmentUploads } from './attachment-uploads'

export const composerDraftLifecycle: DraftLifecycle = {
  suspend: (drafts) => {
    attachmentUploads.pause()
    return Object.fromEntries(
      Object.entries(drafts)
        .filter(([key]) => key.startsWith('composer:'))
        .map(([key, value]) => [
          key,
          {
            ...(value as Composer),
            sending: false,
            uploading: undefined,
            files: (value as Composer).files.flatMap((file) => {
              if (file.directSend) {
                // The old send callback cannot write after suspension. Discard
                // its local recording, but leave uncertain server receipts alone.
                URL.revokeObjectURL(file.url)
                return []
              }
              return [
                {
                  ...file,
                  uploadState: file.attachment ? 'ready' : file.failed ? 'failed' : 'queued',
                },
              ]
            }),
          },
        ]),
    )
  },
  release: (drafts) => {
    attachmentUploads.pause()
    for (const [key, value] of Object.entries(drafts)) {
      if (key.startsWith('composer:'))
        (value as Composer).files.forEach((file) => URL.revokeObjectURL(file.url))
    }
  },
}
