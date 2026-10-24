import { useState } from 'react'
import { isCancelled } from '@web/api/client'
import type { NoticeContent } from '@web/lib/error-notices'
import { ErrorNotice } from './ErrorNotice'

// Dismiss only the presentation: callers may still need field errors or conflict metadata.
export function ActionNotice({ children, ...props }: Omit<NoticeContent, 'onDismiss'>) {
  const [notice, setNotice] = useState({ message: children, dismissed: false })
  if (notice.message !== children) {
    setNotice({ message: children, dismissed: false })
  }
  return (
    <ErrorNotice {...props} onDismiss={() => setNotice({ message: children, dismissed: true })}>
      {isCancelled(children) || notice.dismissed ? null : children}
    </ErrorNotice>
  )
}
