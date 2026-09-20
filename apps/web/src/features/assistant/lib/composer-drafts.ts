import type { DraftLifecycle } from '@web/lib/session-drafts'
import type { Composer } from './audio-capture'

export const composerDraftLifecycle: DraftLifecycle = {
  suspend: (drafts) =>
    Object.fromEntries(
      Object.entries(drafts)
        .filter(([key]) => key.startsWith('composer:'))
        .map(([key, value]) => [
          key,
          { ...(value as Composer), sending: false, uploading: undefined },
        ]),
    ),
  release: (drafts) => {
    for (const [key, value] of Object.entries(drafts)) {
      if (key.startsWith('composer:'))
        (value as Composer).files.forEach((file) => URL.revokeObjectURL(file.url))
    }
  },
}
