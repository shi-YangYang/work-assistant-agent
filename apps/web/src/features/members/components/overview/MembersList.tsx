import type { Member, MemberListItem } from '@paa/api-contracts'
import { Actions } from '@web/components/actions/Actions'
import { detailState } from '@web/utils/navigation'
import { useLocation, useNavigate } from 'react-router'
import layout from '@web/styles/layout.module.css'
import controls from '@web/styles/controls.module.css'
import styles from './MembersPage.module.css'

const created = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

export function MembersList({
  items,
  onAction,
}: {
  items: MemberListItem[]
  onAction: (action: 'name' | 'password' | 'delete', member: Member) => void
}) {
  const location = useLocation()
  const navigate = useNavigate()
  return (
    <div className={styles.list} role="table" aria-label="成员列表">
      <div className={styles.columns} role="row">
        <span role="columnheader">成员</span>
        <span role="columnheader">创建时间</span>
        <span role="columnheader">操作</span>
      </div>
      {items.map((member) => (
        <div className={styles.row} role="row" key={member.id}>
          <div className={styles.member} role="cell">
            <span className={layout.avatar} aria-hidden="true">
              {[...member.name][0]}
            </span>
            <div className={styles.identity}>
              <h3 title={member.name}>{member.name}</h3>
              <p title={member.username}>{member.username}</p>
            </div>
          </div>
          <span className={styles.created} role="cell">
            <span className={styles['date-label']}>创建于 </span>
            <time dateTime={member.createdAt}>{created.format(new Date(member.createdAt))}</time>
          </span>
          <div className={styles['row-actions']} role="cell">
            <Actions>
              <button
                role="menuitem"
                onClick={() => {
                  const params = new URLSearchParams({
                    view: 'work',
                    scope: 'current',
                    member: member.id,
                    members: 'all',
                  })
                  navigate(`/team?${params}`, { state: detailState(location) })
                }}
              >
                查看工作
              </button>
              <button role="menuitem" onClick={() => onAction('name', member)}>
                编辑姓名
              </button>
              <button role="menuitem" onClick={() => onAction('password', member)}>
                重置密码
              </button>
              <button
                role="menuitem"
                className={controls.danger}
                onClick={() => onAction('delete', member)}
              >
                删除账号
              </button>
            </Actions>
          </div>
        </div>
      ))}
    </div>
  )
}
