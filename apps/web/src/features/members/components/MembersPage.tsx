import layoutStyles from '../../../styles/layout.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import recordLayoutStyles from '../../../components/RecordLayout.module.css'
import type { Member, Page } from '@paa/api-contracts'
import { Actions } from '@web/components/Actions'
import { RecordEmpty } from '@web/components/RecordEmpty'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { membersPath, updateMember } from '@web/features/members/api/requests'
import { DeleteMember } from '@web/features/members/components/DeleteMember'
import { MemberForm } from '@web/features/members/components/MemberForm'
import { useResource } from '@web/hooks/useResource'
import { useWorkspace } from '@web/lib/workspace'
import { UserPlus, Users } from 'lucide-react'
import { useState } from 'react'

export function MembersPage() {
  const { data, error, refresh } = useResource<Page<Member>>(membersPath())
  const [create, setCreate] = useState(false)
  const [reset, setReset] = useState<Member | null>(null)
  const [deleting, setDeleting] = useState<Member | null>(null)
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
    <div className={layoutStyles['page']} data-scroll-container>
      <div className={`${layoutStyles['page-heading']}`}>
        <div>
          <h2>成员管理</h2>
        </div>
        <button
          className={controlsStyles['primary']}
          onClick={() => {
            setFailure('')
            setCreate(true)
          }}
        >
          <UserPlus size={16} />
          添加成员
        </button>
      </div>
      <ErrorNotice retry={refresh}>{failure || error}</ErrorNotice>
      <div className={recordLayoutStyles['record-list']}>
        {!data && !error && (
          <p className={recordLayoutStyles['records-loading']} role="status">
            正在读取成员…
          </p>
        )}
        {data && !data.items.length && (
          <RecordEmpty
            icon={<Users size={26} />}
            title="还没有成员"
            action={
              <button className={controlsStyles['primary']} onClick={() => setCreate(true)}>
                <UserPlus size={16} />
                添加成员
              </button>
            }
          >
            添加公司成员，一起记录与跟进工作。
          </RecordEmpty>
        )}
        {data?.items.map((member) => (
          <div className={recordLayoutStyles['record-row']} key={member.id}>
            <span className={layoutStyles['avatar']}>{member.name.slice(0, 1)}</span>
            <div className={recordLayoutStyles['record-main']}>
              <h3>{member.name}</h3>
              <p>
                {member.username} · {member.role === 'admin' ? '管理员' : '用户'} ·{' '}
                {member.active ? '正常' : '已停用'}
              </p>
            </div>
            <Actions>
              <button role="menuitem" onClick={() => setReset(member)}>
                重置密码
              </button>
              <button role="menuitem" onClick={() => void change(member)}>
                {member.active ? '停用账号' : '启用账号'}
              </button>
              <button
                role="menuitem"
                className={controlsStyles['danger']}
                onClick={() => setDeleting(member)}
              >
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
        <MemberForm
          key={reset?.id ?? 'create'}
          member={reset}
          onClose={() => {
            setCreate(false)
            setReset(null)
          }}
          onSaved={() => {
            setCreate(false)
            setReset(null)
            refresh()
            notify(reset ? '密码已重置，该成员需使用新密码重新登录' : '成员已创建')
          }}
        />
      )}
    </div>
  )
}
