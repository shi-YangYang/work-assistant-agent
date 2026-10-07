import layout from '@web/styles/layout.module.css'
import controls from '@web/styles/controls.module.css'
import styles from './MembersPage.module.css'
import type { Member, MemberListItem, Page } from '@paa/api-contracts'
import { Pagination } from '@web/components/actions/Pagination'
import { RecordEmpty } from '@web/components/content/RecordEmpty'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { membersPath } from '@web/features/members/api/requests'
import { DeleteMember } from '../actions/DeleteMember'
import { MemberForm } from '../forms/MemberForm'
import { MemberNameForm } from '../forms/MemberNameForm'
import { MembersList } from './MembersList'
import { MembersToolbar } from './MembersToolbar'
import { useResource } from '@web/hooks/useResource'
import { useWorkspace } from '@web/lib/workspace'
import { RefreshCw, Search, UserPlus, Users } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useLocation, useSearchParams } from 'react-router'

type Action = { kind: 'name' | 'password' | 'delete'; member: Member } | { kind: 'create' }
const PAGE_SIZE = 20

export function MembersPage() {
  const { data, error, refresh } = useResource<Page<MemberListItem>>(membersPath())
  const [action, setAction] = useState<Action | null>(null)
  const [params, setParams] = useSearchParams()
  const location = useLocation()
  const query = params.get('q') ?? ''
  const keyword = query.trim().toLocaleLowerCase()
  const items = data?.items.filter((member) =>
    [member.name, member.username].some((value) => value.toLocaleLowerCase().includes(keyword)),
  )
  const requestedPage = Number(params.get('page') ?? 1)
  const totalPages = Math.max(1, Math.ceil((items?.length ?? 0) / PAGE_SIZE))
  const page = Math.min(
    Number.isSafeInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1,
    totalPages,
  )
  const offset = (page - 1) * PAGE_SIZE
  const visibleItems = items?.slice(offset, offset + PAGE_SIZE) ?? []
  useEffect(() => {
    if (!data || params.get('page') === (page > 1 ? String(page) : null)) return
    const next = new URLSearchParams(params)
    if (page > 1) next.set('page', String(page))
    else next.delete('page')
    setParams(next, { replace: true, state: location.state })
  }, [data, page, params, setParams, location.state])
  const { notify } = useWorkspace()
  const goToPage = (value: number) => {
    const next = new URLSearchParams(params)
    if (value > 1) next.set('page', String(value))
    else next.delete('page')
    setParams(next, { state: location.state })
  }
  const search = (value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set('q', value)
    else next.delete('q')
    next.delete('status')
    next.delete('page')
    setParams(next, { replace: true, state: location.state })
  }
  const saved = (message: string) => {
    setAction(null)
    refresh()
    notify(message)
  }
  return (
    <div className={`${layout.page} ${styles.page}`} data-scroll-container>
      <div className={`${layout['page-heading']} ${styles.heading}`}>
        <div className={styles.title}>
          <h2>成员管理</h2>
          {data && <span className={styles.total}>{data.items.length} 人</span>}
        </div>
        <div className={styles.actions}>
          <button
            className={controls['icon-button']}
            aria-label="刷新成员"
            title="刷新成员"
            onClick={refresh}
          >
            <RefreshCw size={16} />
          </button>
          <button className={controls.primary} onClick={() => setAction({ kind: 'create' })}>
            <UserPlus size={16} />
            添加成员
          </button>
        </div>
      </div>
      <MembersToolbar
        query={query}
        change={search}
        total={data?.items.length}
        matched={items?.length}
      />
      <ErrorNotice retry={refresh}>{error}</ErrorNotice>
      {!data && !error && (
        <p className={styles.loading} role="status">
          正在读取成员…
        </p>
      )}
      {items &&
        (items.length ? (
          <MembersList
            items={visibleItems}
            onAction={(kind, member) => setAction({ kind, member })}
          />
        ) : (
          <RecordEmpty
            icon={keyword ? <Search size={26} /> : <Users size={26} />}
            title={keyword ? '没有匹配的成员' : '还没有成员'}
            action={
              keyword ? (
                <button onClick={() => search('')}>清除搜索</button>
              ) : (
                <button className={controls.primary} onClick={() => setAction({ kind: 'create' })}>
                  添加第一位成员
                </button>
              )
            }
          >
            {keyword ? '试试其他姓名或账号。' : '添加公司成员，一起记录与跟进工作。'}
          </RecordEmpty>
        ))}
      {items && (
        <div className={styles.pagination}>
          <span className={styles.count}>
            {items.length
              ? `显示 ${offset + 1}–${Math.min(offset + PAGE_SIZE, items.length)}，共 ${items.length} 人`
              : '共 0 人'}
          </span>
          <Pagination
            page={page}
            hasNext={page < totalPages}
            previous={() => goToPage(page - 1)}
            next={() => goToPage(page + 1)}
          />
        </div>
      )}
      {action?.kind === 'delete' && (
        <DeleteMember
          member={action.member}
          onClose={() => setAction(null)}
          onDeleted={() => saved('账号已删除，历史工作和报告已保留')}
        />
      )}
      {action?.kind === 'name' && (
        <MemberNameForm
          member={action.member}
          onClose={() => setAction(null)}
          onSaved={() => saved('姓名已更新')}
        />
      )}
      {(action?.kind === 'create' || action?.kind === 'password') && (
        <MemberForm
          member={action.kind === 'password' ? action.member : null}
          onClose={() => setAction(null)}
          onSaved={() =>
            saved(
              action.kind === 'password' ? '密码已重置，该成员需使用新密码重新登录' : '成员已创建',
            )
          }
        />
      )}
    </div>
  )
}
