import { useRef, useState } from 'react'
import type { Announcement } from '@paa/api-contracts'
import { ApiError, isCancelled } from '@web/api/client'
import { ConfirmDialog } from '@web/components/overlays/ConfirmDialog'
import { useWorkspace } from '@web/lib/workspace'
import { deleteAnnouncement } from '../api/requests'

export type DeletingAnnouncement = Pick<Announcement, 'id' | 'title' | 'revision'>

export function DeleteAnnouncementDialog({
  item,
  onClose,
  onDeleted,
  onConflict,
}: {
  item: DeletingAnnouncement
  onClose: () => void
  onDeleted: () => void
  onConflict: () => void
}) {
  const { notify } = useWorkspace()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  const [unavailable, setUnavailable] = useState(false)
  const pending = useRef<{ revision: number; key: string } | null>(null)
  const inFlight = useRef(false)
  const remove = async () => {
    if (inFlight.current || unavailable) return
    const request = pending.current ?? { revision: item.revision, key: crypto.randomUUID() }
    pending.current = request
    inFlight.current = true
    setBusy(true)
    setError('')
    try {
      await deleteAnnouncement(item.id, request.revision, request.key)
      window.dispatchEvent(new Event('paa-notifications-changed'))
      notify('公告已删除')
      onDeleted()
    } catch (failure) {
      if (!isCancelled(failure)) setError(failure as Error)
      if (failure instanceof ApiError && [404, 409].includes(failure.status)) {
        setUnavailable(true)
        setError(
          failure.status === 409
            ? '公告已更新，请关闭弹窗后重新查看再删除。'
            : '公告已删除或不可用。',
        )
        onConflict()
      }
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }
  return (
    <ConfirmDialog
      title="删除公告"
      confirmLabel="删除"
      danger
      busy={busy}
      confirmDisabled={unavailable}
      error={error}
      onConfirm={() => void remove()}
      onClose={onClose}
    >
      <p>确定删除「{item.title}」？删除后所有成员都将无法查看，且无法恢复。</p>
    </ConfirmDialog>
  )
}
