import { useEffect, useState } from 'react'
import { isCancelled } from '@web/api/client'
import type { NoticeContent } from '@web/lib/error-notices'
import { ErrorNotice } from './ErrorNotice'

// Dismiss only the presentation: callers may still need field errors or conflict metadata.
export function ActionNotice({ children, ...props }: Omit<NoticeContent, 'onDismiss'>) {
  const [dismissed, setDismissed] = useState<NoticeContent['children']>(null)
  useEffect(() => setDismissed(null), [children])
  return (
    <ErrorNotice {...props} onDismiss={() => setDismissed(children)}>
      {isCancelled(children) || children === dismissed ? null : children}
    </ErrorNotice>
  )
}
