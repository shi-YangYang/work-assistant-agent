import layoutStyles from '../../../styles/layout.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import type { Member } from '@paa/api-contracts'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Modal } from '@web/components/Modal'
import { useResource } from '@web/hooks/useResource'
import { useWorkspace } from '@web/lib/workspace'
import {
  deleteMember,
  memberDeletionPath,
  type MemberDeletionImpact,
} from '@web/features/members/api/requests'
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
  const { notify } = useWorkspace()
  const impact = useResource<MemberDeletionImpact>(memberDeletionPath(member))
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<Error | string>('')
  return (
    <Modal title="删除账号" onClose={onClose}>
      <p>
        确定删除 {member.name}（{member.username}）的账号？
      </p>
      <p>该成员将退出登录，待处理任务和汇报提醒会停止。历史工作、报告和原始消息会保留。</p>
      <p>之后可用同一账号名重新创建，或通过钉钉重新注册；新账号不会继承旧资料。</p>
      {impact.data ? (
        <p>
          同时删除 {impact.data.voiceprints} 份声纹和 {impact.data.recordings}{' '}
          份登记录音，释放登记额度。已离线的桌面副本不受影响。
        </p>
      ) : (
        !impact.error && <p role="status">正在核对关联资料…</p>
      )}
      <ErrorNotice retry={impact.refresh}>{failure || impact.error}</ErrorNotice>
      <div className={layoutStyles['form-actions']}>
        <button type="button" onClick={onClose}>
          取消
        </button>
        <BusyButton
          className={controlsStyles['danger']}
          busy={busy}
          disabled={!impact.data || !!impact.error}
          onClick={async () => {
            setBusy(true)
            setFailure('')
            try {
              const result = await deleteMember(member, undefined)
              if (result.cleanupPending)
                notify('账号已删除，声纹文件正在清理；可在公司声纹中查看进度。')
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
