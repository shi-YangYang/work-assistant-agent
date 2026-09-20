import type { Member } from '@paa/api-contracts'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Modal } from '@web/components/Modal'
import { deleteMember } from '@web/features/members/api/requests'
import { useState } from 'react'

export function DeleteMember({
  member,
  onClose,
  onDeleted,
}: {
  member: Member
  onClose: () => void
  onDeleted: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<Error | string>('')
  return (
    <Modal title="删除账号" onClose={onClose}>
      <p>
        确定删除 {member.name}（{member.username}）的账号？
      </p>
      <p>该成员将退出登录，待处理任务和汇报提醒会停止。历史工作、报告和原始消息会保留。</p>
      <p>之后可用同一账号名重新创建，或通过钉钉重新注册；新账号不会继承旧资料。</p>
      <ErrorNotice>{failure}</ErrorNotice>
      <div className="form-actions">
        <button type="button" onClick={onClose}>
          取消
        </button>
        <BusyButton
          className="danger"
          busy={busy}
          onClick={async () => {
            setBusy(true)
            setFailure('')
            try {
              await deleteMember(member, undefined)
              onDeleted()
            } catch (error) {
              setFailure(error as Error)
            } finally {
              setBusy(false)
            }
          }}
        >
          删除账号
        </BusyButton>
      </div>
    </Modal>
  )
}
