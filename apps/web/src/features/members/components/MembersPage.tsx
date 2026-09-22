import type { Member, Page } from '@paa/api-contracts'
import { Actions } from '@web/components/Actions'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Modal } from '@web/components/Modal'
import {
  createMember,
  membersPath,
  resetMemberPassword,
  updateMember,
} from '@web/features/members/api/requests'
import { DeleteMember } from '@web/features/members/components/DeleteMember'
import { useResource } from '@web/hooks/useResource'
import { useWorkspace } from '@web/lib/workspace'
import { UserPlus } from 'lucide-react'
import { useState } from 'react'

export function MembersPage() {
  const { data, error, refresh } = useResource<Page<Member>>(membersPath())
  const [create, setCreate] = useState(false)
  const [reset, setReset] = useState<Member | null>(null)
  const [deleting, setDeleting] = useState<Member | null>(null)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<Error | string>('')
  const { notify } = useWorkspace()
  async function change(member: Member) {
    if (
      !window.confirm(`${member.active ? '停用' : '启用'} ${member.name} 的账号？历史记录会保留。`)
    )
      return
    try {
      await updateMember(member, { active: !member.active })
      refresh()
    } catch (e) {
      setFailure(e as Error)
    }
  }
  return (
    <div className="page">
      <div className="page-heading">
        <div>
          <h2>成员管理</h2>
        </div>
        <button className="primary" onClick={() => setCreate(true)}>
          <UserPlus size={16} />
          添加成员
        </button>
      </div>
      <ErrorNotice retry={refresh}>{failure || error}</ErrorNotice>
      <div className="record-list">
        {data?.items.map((member) => (
          <div className="record-row" key={member.id}>
            <span className="avatar">{member.name.slice(0, 1)}</span>
            <div className="record-main">
              <h3>{member.name}</h3>
              <p>
                {member.username} · {member.role === 'admin' ? '管理员' : '用户'} ·{' '}
                {member.active ? '正常' : '已停用'}
              </p>
            </div>
            <Actions>
              <button role="menuitem" onClick={() => setReset(member)}>
                重置临时密码
              </button>
              <button role="menuitem" onClick={() => void change(member)}>
                {member.active ? '停用账号' : '启用账号'}
              </button>
              <button role="menuitem" className="danger" onClick={() => setDeleting(member)}>
                删除账号
              </button>
            </Actions>
          </div>
        ))}
      </div>
      {deleting && (
        <DeleteMember
          member={deleting}
          onClose={() => setDeleting(null)}
          onDeleted={() => {
            setDeleting(null)
            refresh()
            notify('账号已删除，历史工作和报告已保留')
          }}
        />
      )}
      {(create || reset) && (
        <Modal
          title={reset ? `重置 ${reset.name} 的密码` : '添加成员'}
          onClose={() => {
            setCreate(false)
            setReset(null)
          }}
        >
          <form
            onSubmit={async (e) => {
              e.preventDefault()
              const form = new FormData(e.currentTarget)
              setBusy(true)
              try {
                if (reset)
                  await resetMemberPassword(reset, {
                    password: form.get('password'),
                  })
                else
                  await createMember({
                    name: form.get('name'),
                    username: form.get('username'),
                    role: 'employee',
                    password: form.get('password'),
                  })
                setCreate(false)
                setReset(null)
                refresh()
                notify('已保存，请将账号与临时密码交给成员；首次登录需修改')
              } catch (e) {
                setFailure(e as Error)
              } finally {
                setBusy(false)
              }
            }}
          >
            {!reset && (
              <>
                <label>
                  姓名
                  <input name="name" required maxLength={80} />
                </label>
                <label>
                  账号
                  <input
                    name="username"
                    required
                    pattern="[a-zA-Z0-9._@-]{3,80}"
                    autoComplete="off"
                  />
                </label>
              </>
            )}
            <label>
              临时密码
              <input
                name="password"
                type="password"
                autoComplete="new-password"
                required
                minLength={reset ? 12 : 4}
                maxLength={128}
              />
            </label>
            <small>至少 {reset ? 12 : 4} 位。请通过公司认可的方式交给本人。</small>
            <ErrorNotice>{failure}</ErrorNotice>
            <div className="form-actions">
              <button
                type="button"
                onClick={() => {
                  setCreate(false)
                  setReset(null)
                }}
              >
                取消
              </button>
              <BusyButton busy={busy} className="primary">
                保存
              </BusyButton>
            </div>
          </form>
        </Modal>
      )}
    </div>
  )
}
