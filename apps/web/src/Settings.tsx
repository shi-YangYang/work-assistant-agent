import { useCursorPage, filterParams } from './list-state'
import { Pagination, WorkFilters, PeriodFilter } from './ListControls'
import type { DateRange, TeamDetail, TeamMetrics } from '@paa/api-contracts'
import { ReportActions } from './RecordManagement'
import { companyTimezones, timezoneLabel } from './timezones'
import { TimeField } from './ui'
import { usePagedResource } from './paged-resource'
import { useEffect, useState } from 'react'
import { Link, useLocation, useParams, useSearchParams } from 'react-router'
import { ChevronRight, RefreshCw, UserPlus } from 'lucide-react'
import type {
  Member,
  Page,
  Report,
  Rules,
  Schedule,
  Team,
  Theme,
  Work,
  WorkMessage,
} from '@paa/api-contracts'
import { api, dateLabel, useResource, write } from './api'
import { useWorkspace } from './workspace'
import { ConflictRecovery, Actions, BusyButton, Empty, ErrorNotice, Modal } from './ui'
import { MessageCard } from './Assistant'
import { WorkList } from './Records'
import { detailState } from './navigation'

function applyTheme(value: Theme) {
  localStorage.setItem('paa.company.theme', value)
  document.documentElement.dataset.theme =
    value === 'system'
      ? matchMedia('(prefers-color-scheme: dark)').matches
        ? 'dark'
        : 'light'
      : value
}
export function AppearancePage() {
  const [value, setValue] = useState<Theme>(
    () => (localStorage.getItem('paa.company.theme') as Theme) || 'system',
  )
  useEffect(() => {
    applyTheme(value)
    const media = matchMedia('(prefers-color-scheme: dark)')
    const change = () => applyTheme(value)
    media.addEventListener('change', change)
    return () => media.removeEventListener('change', change)
  }, [value])
  return (
    <div className="settings-page">
      <h2>外观</h2>
      <div className="theme-options">
        {(['light', 'dark', 'system'] as const).map((theme) => (
          <button
            key={theme}
            className={theme === value ? 'selected' : ''}
            onClick={() => setValue(theme)}
            aria-pressed={theme === value}
          >
            <div className={`theme-preview ${theme}`}>
              <i />
              <span />
            </div>
            {{ light: '浅色', dark: '深色', system: '跟随系统' }[theme]}
          </button>
        ))}
      </div>
    </div>
  )
}
export function AccountPage({
  onLogout,
  force = false,
  member,
}: {
  onLogout: () => void
  force?: boolean
  member?: Member
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  return (
    <div className={force ? 'password-reset' : 'settings-page account-page'}>
      {!force && (
        <>
          <h2>账户</h2>
          <Link to="/settings/support">问题反馈与处理结果</Link>
          <div className="account-summary">
            <span className="avatar">{member?.name.slice(0, 1)}</span>
            <div>
              <h3>{member?.name}</h3>
              <p className="muted">
                {member?.username} · {member?.role === 'admin' ? '管理员' : '用户'}
              </p>
            </div>
          </div>
        </>
      )}
      <form
        className="panel password-form"
        onSubmit={async (e) => {
          e.preventDefault()
          const data = new FormData(e.currentTarget)
          if (data.get('new') !== data.get('confirm')) {
            setError('两次新密码不一致')
            return
          }
          setBusy(true)
          try {
            await write('/auth/password', {
              currentPassword: data.get('current'),
              newPassword: data.get('new'),
            })
            onLogout()
          } catch (e) {
            setError(e as Error)
          } finally {
            setBusy(false)
          }
        }}
      >
        <h3>修改密码</h3>
        <label>
          当前密码
          <input
            name="current"
            type="password"
            autoComplete="current-password"
            required
            maxLength={128}
          />
        </label>
        <label>
          新密码
          <input
            name="new"
            type="password"
            autoComplete="new-password"
            required
            minLength={12}
            maxLength={128}
          />
        </label>
        <label>
          确认新密码
          <input
            name="confirm"
            type="password"
            autoComplete="new-password"
            required
            minLength={12}
            maxLength={128}
          />
        </label>
        <small>至少 12 位。修改后所有已登录设备均需重新登录。</small>
        <ErrorNotice>{error}</ErrorNotice>
        <div className="form-actions">
          <BusyButton busy={busy} className="primary">
            保存密码并重新登录
          </BusyButton>
        </div>
      </form>
      {!force && (
        <button
          className="danger"
          onClick={async () => {
            try {
              await write('/auth/logout', {})
              onLogout()
            } catch (e) {
              setError(e as Error)
            }
          }}
        >
          退出登录
        </button>
      )}
    </div>
  )
}
export function RulesPage() {
  const { data, error, refresh } = useResource<Rules>('/settings/report-rules')
  const { identity, drafts, setDraft, notify } = useWorkspace()
  const value = (drafts.rules as Rules | undefined) ?? data
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<Error | string>('')
  const canEdit = identity.member.role === 'admin'
  const update = (kind: 'daily' | 'weekly', schedule: Schedule) => {
    if (value) setDraft('rules', { ...value, [kind]: schedule })
  }
  return (
    <div className="settings-page">
      <h2>汇报规则</h2>
      <ErrorNotice retry={refresh}>{failure || error}</ErrorNotice>
      {value && !canEdit && (
        <div className="rule-summary">
          <p className="muted">公司时区：{timezoneLabel(value.timezone)}</p>
          {(['daily', 'weekly'] as const).map((kind) => (
            <section className="panel schedule-panel" key={kind}>
              <div className="row-between">
                <h3>{kind === 'daily' ? '日报' : '周报'}</h3>
                <span className="status">{value[kind].enabled ? '已启用' : '未启用'}</span>
              </div>
              {value[kind].enabled ? (
                <dl className="summary-grid">
                  <div className="full-field">
                    <dt>周期</dt>
                    <dd>
                      {value[kind].days
                        .map((day) => ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][day])
                        .join('、')}
                    </dd>
                  </div>
                  <div>
                    <dt>草稿生成</dt>
                    <dd>{value[kind].generateTime}</dd>
                  </div>
                  <div>
                    <dt>提交截止</dt>
                    <dd>{value[kind].deadline}</dd>
                  </div>
                </dl>
              ) : (
                <p className="muted">可在我的报告中手动准备报告。</p>
              )}
              {value[kind].enabled && (
                <p className="muted">
                  {value[kind].reminders === false
                    ? '站内提醒已关闭'
                    : `草稿就绪、截止前 ${value[kind].beforeMinutes ?? 30} 分钟及逾期后提醒`}
                </p>
              )}
              {value.effectivePeriods?.[kind] && (
                <p className="muted">当前设置从 {value.effectivePeriods[kind]} 起的周期生效</p>
              )}
            </section>
          ))}
        </div>
      )}
      {value && canEdit && (
        <form
          className="rules-form"
          onSubmit={async (e) => {
            e.preventDefault()
            setBusy(true)
            try {
              await write(
                '/settings/report-rules',
                {
                  timezone: value.timezone,
                  daily: value.daily,
                  weekly: value.weekly,
                  expectedRevision: value.revision,
                },
                'PUT',
              )
              setDraft('rules', undefined)
              refresh()
              notify('汇报规则已保存，从后续安排生效')
            } catch (e) {
              setFailure(e as Error)
            } finally {
              setBusy(false)
            }
          }}
        >
          <label className="timezone-field">
            公司时区
            <select
              value={value.timezone}
              disabled={!canEdit}
              onChange={(e) => setDraft('rules', { ...value, timezone: e.target.value })}
            >
              {[...new Set([...companyTimezones, value.timezone])].map((zone) => (
                <option key={zone} value={zone}>
                  {timezoneLabel(zone)}
                </option>
              ))}
            </select>
          </label>
          {(['daily', 'weekly'] as const).map((kind) => (
            <fieldset disabled={!canEdit} className="panel schedule-panel" key={kind}>
              <div className="row-between">
                <h3>{kind === 'daily' ? '日报' : '周报'}</h3>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={value[kind].enabled}
                    onChange={(e) => update(kind, { ...value[kind], enabled: e.target.checked })}
                  />
                  启用汇报安排
                </label>
              </div>
              <div className="weekdays">
                {['一', '二', '三', '四', '五', '六', '日'].map((day, index) => (
                  <label key={day}>
                    <input
                      type={kind === 'weekly' ? 'radio' : 'checkbox'}
                      name={kind}
                      checked={value[kind].days.includes(index)}
                      onChange={(e) =>
                        update(kind, {
                          ...value[kind],
                          days:
                            kind === 'weekly'
                              ? [index]
                              : e.target.checked
                                ? [...value[kind].days, index].sort()
                                : value[kind].days.filter((d) => d !== index),
                        })
                      }
                    />
                    <span>周{day}</span>
                  </label>
                ))}
              </div>
              <div className="two-columns">
                <label>
                  草稿生成时间
                  <TimeField
                    required={value[kind].enabled}
                    value={value[kind].generateTime}
                    onChange={(time) => update(kind, { ...value[kind], generateTime: time })}
                  />
                </label>
                <label>
                  提交截止时间
                  <TimeField
                    required={value[kind].enabled}
                    value={value[kind].deadline}
                    onChange={(time) => update(kind, { ...value[kind], deadline: time })}
                  />
                </label>
              </div>
              <div className="reminder-settings">
                <label className="check">
                  <input
                    type="checkbox"
                    checked={value[kind].reminders ?? true}
                    onChange={(e) => update(kind, { ...value[kind], reminders: e.target.checked })}
                  />
                  站内提醒
                </label>
                <label>
                  截止前提醒（分钟）
                  <input
                    type="number"
                    min={0}
                    max={1440}
                    disabled={value[kind].reminders === false}
                    value={value[kind].beforeMinutes ?? 30}
                    onChange={(e) =>
                      update(kind, { ...value[kind], beforeMinutes: Number(e.target.value) })
                    }
                  />
                </label>
              </div>
              {value.effectivePeriods?.[kind] && (
                <p className="muted">当前设置从 {value.effectivePeriods[kind]} 起的周期生效</p>
              )}
            </fieldset>
          ))}
          <p className="muted">
            时间按公司时区计算。修改后不重复生成历史周期，也不会改写已提交报告。
          </p>
          {failure && canEdit && (
            <ConflictRecovery<Rules>
              load={() => api('/settings/report-rules')}
              render={(latest) => (
                <>
                  <p>公司时区：{timezoneLabel(latest.timezone)}</p>
                  {(['daily', 'weekly'] as const).map((kind) => (
                    <p key={kind}>
                      {kind === 'daily' ? '日报' : '周报'}：
                      {latest[kind].enabled
                        ? `${latest[kind].generateTime} 生成，${latest[kind].deadline} 截止`
                        : '自动生成未启用'}
                    </p>
                  ))}
                </>
              )}
              keep={(latest) => {
                setDraft('rules', { ...value, revision: latest.revision })
                setFailure('')
              }}
              replace={(latest) => {
                setDraft('rules', latest)
                setFailure('')
              }}
            />
          )}
          <div className="form-actions editor-actions">
            <BusyButton busy={busy} className="primary">
              保存汇报规则
            </BusyButton>
          </div>
        </form>
      )}
    </div>
  )
}
export function MembersPage() {
  const { data, error, refresh } = useResource<Page<Member>>('/members')
  const [create, setCreate] = useState(false)
  const [reset, setReset] = useState<Member | null>(null)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<Error | string>('')
  const { notify } = useWorkspace()
  async function change(member: Member) {
    if (
      !window.confirm(`${member.active ? '停用' : '启用'} ${member.name} 的账号？历史记录会保留。`)
    )
      return
    try {
      await write(`/members/${member.id}`, { active: !member.active }, 'PATCH')
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
            </Actions>
          </div>
        ))}
      </div>
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
                  await write(`/members/${reset.id}/reset-password`, {
                    password: form.get('password'),
                  })
                else
                  await write('/members', {
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
                minLength={12}
                maxLength={128}
              />
            </label>
            <small>至少 12 位。请通过公司认可的方式交给本人。</small>
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
export function TeamPage() {
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const { data, error, refresh } = useResource<Team>(`/team?${params}`, 30000)
  const update = (values: Record<string, string>) =>
    setParams(filterParams(params, values), { replace: true })
  const details = (metric: string) =>
    `/team/details?${new URLSearchParams({ ...Object.fromEntries(params), metric, ...(data ? { period: 'custom', start: data.range.start, end: data.range.end } : {}) })}`
  return (
    <div className="page">
      <div className="page-heading">
        <div>
          <h2>团队看板</h2>
          <p>{data ? `更新于 ${dateLabel(data.updatedAt)}` : '查看员工已确认的进展与上报'}</p>
        </div>
        <div className="inline">
          <Link className="button" to="/team/reports" state={detailState(location)}>
            汇报情况
          </Link>
          <button onClick={refresh}>
            <RefreshCw size={16} />
            刷新
          </button>
        </div>
      </div>
      <div className="filters team-filters">
        <input
          aria-label="搜索员工"
          placeholder="搜索员工"
          value={params.get('q') || ''}
          onChange={(e) => update({ q: e.target.value })}
        />
        <select
          aria-label="员工范围"
          value={params.get('members') || 'active'}
          onChange={(e) => update({ members: e.target.value })}
        >
          <option value="active">在职员工</option>
          <option value="inactive">停用员工</option>
          <option value="all">全部员工</option>
        </select>
        <select
          aria-label="进展状态"
          value={params.get('status') || ''}
          onChange={(e) => update({ status: e.target.value })}
        >
          <option value="">全部工作状态</option>
          <option value="in_progress">进行中</option>
          <option value="blocked">有阻碍</option>
          <option value="done">已完成</option>
        </select>
        <PeriodFilter params={params} range={data?.range} change={update} />
      </div>
      <ErrorNotice retry={refresh}>{error}</ErrorNotice>
      {data && (
        <>
          <div className="metrics">
            <Link
              to={details('messages')}
              state={detailState(location)}
              title="所选期间发送过工作消息的员工"
            >
              <small>已上报员工</small>
              <strong>
                {data.metrics.reported}
                <span> / {data.metrics.members}</span>
              </strong>
            </Link>
            <Link
              to={details('blocked')}
              state={detailState(location)}
              title="期间有确认更新、期末仍未完成的阻碍工作"
            >
              <small>有阻碍的工作</small>
              <strong>{data.metrics.blocked}</strong>
            </Link>
            <Link
              to={details('reports')}
              state={detailState(location)}
              title="所选期间实际提交过的报告，每份只计一次"
            >
              <small>已提交报告</small>
              <strong>{data.metrics.reports}</strong>
            </Link>
          </div>
          {data.items.length ? (
            <div className="record-list">
              {data.items.map((item) => (
                <Link
                  className="record-row team-row"
                  to={`/team/${item.member.id}`}
                  state={detailState(location)}
                  key={item.member.id}
                >
                  <span className="avatar">{item.member.name.slice(0, 1)}</span>
                  <div className="record-main">
                    <h3>
                      {item.member.name}
                      {!item.member.active && <small> · 已停用</small>}
                    </h3>
                    <p className="record-summary">
                      {item.work[0]?.summary || '本期无符合条件的工作更新'}
                    </p>
                    <small>
                      {item.workCount} 项工作 · {item.reportCount} 份报告
                    </small>
                  </div>
                  <small className="record-updated">
                    {item.lastMessageAt
                      ? `本期最近上报 ${dateLabel(item.lastMessageAt)}`
                      : '本期未上报'}
                  </small>
                  {item.blockedCount > 0 && (
                    <span className="status blocked">{item.blockedCount} 项阻碍</span>
                  )}
                  <ChevronRight size={18} />
                </Link>
              ))}
            </div>
          ) : (
            <Empty title="没有符合条件的员工">可调整筛选条件，或先添加员工账号。</Empty>
          )}
        </>
      )}
      {!data && !error && <p className="muted">正在读取看板…</p>}
      <Link className="mobile-only" to="/members">
        管理成员
      </Link>
    </div>
  )
}
export function TeamMetricPage() {
  const location = useLocation()
  const [params] = useSearchParams()
  const query = new URLSearchParams(params)
  query.delete('after')
  const list = useCursorPage<TeamDetail, { range: DateRange; metrics: TeamMetrics; total: number }>(
    `/team/details?${query}`,
  )
  const metric = params.get('metric') || 'messages'
  return (
    <div className="page">
      <div className="page-heading">
        <div>
          <h2>
            {{ messages: '本期工作上报', blocked: '本期阻碍工作', reports: '本期已提交报告' }[
              metric
            ] || '统计明细'}
          </h2>
          {list.data && (
            <p>
              {list.data.range.start} — {list.data.range.end} ·{' '}
              {metric === 'messages'
                ? `${list.data.metrics.reported} 位员工，${list.data.total} 条消息`
                : `${list.data.total} 条记录`}
            </p>
          )}
        </div>
      </div>
      <ErrorNotice retry={list.refresh}>{list.error}</ErrorNotice>
      {list.data &&
        (list.data.items.length ? (
          <div className="record-list">
            {list.data.items.map((item) => (
              <Link
                key={item.id}
                to={item.href}
                state={detailState(location)}
                className="record-row"
              >
                <div className="record-main">
                  <h3>{item.title}</h3>
                  <p>
                    {item.member.name}
                    {item.work?.blocker ? ` · ${item.work.blocker}` : ''}
                  </p>
                </div>
                <time>{dateLabel(item.at)}</time>
                <ChevronRight size={18} />
              </Link>
            ))}
          </div>
        ) : (
          <Empty title="本期没有符合条件的记录" />
        ))}
      {list.data && (
        <Pagination
          page={list.page}
          hasNext={!!list.data.nextCursor}
          previous={list.previous}
          next={list.next}
        />
      )}
    </div>
  )
}
export function TeamMemberPage() {
  const location = useLocation()
  const { id } = useParams()
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') ?? 'work'
  const kind = params.get('kind') ?? 'daily'
  const work = useCursorPage<Work, { member: Member }>(
    `/team/members/${id}/work?${new URLSearchParams({ q: params.get('q') || '', status: params.get('status') || '' })}`,
  )
  const messages = usePagedResource<WorkMessage>(`/team/members/${id}/messages`, 'createdAt', 30000)
  const reports = useResource<Page<Report>>(
    tab === 'reports' ? `/team/members/${id}/reports?kind=${kind}` : null,
    30000,
  )
  const nextCursor = messages.data?.nextCursor
  return (
    <div className="page">
      <div className="page-heading">
        <div>
          <h2>{work.data?.member.name ?? '成员详情'}</h2>
        </div>
      </div>
      <div className="tabs">
        {[
          ['work', '工作进展'],
          ['messages', '原始上报'],
          ['reports', '报告'],
        ].map(([key, label]) => (
          <button
            key={key}
            className={tab === key ? 'active' : ''}
            onClick={() => setParams({ tab: key, kind }, { replace: true, state: location.state })}
          >
            {label}
          </button>
        ))}
      </div>
      <ErrorNotice>{work.error || messages.error || reports.error}</ErrorNotice>
      {tab === 'work' && (
        <>
          <WorkFilters
            query={params.get('q') || ''}
            status={params.get('status') || ''}
            change={work.filter}
          />
          {work.data ? (
            work.data.items.length ? (
              <WorkList items={work.data.items} refresh={work.refresh} />
            ) : (
              <Empty
                title={
                  params.get('q') || params.get('status') ? '没有符合条件的工作' : '尚无已确认进展'
                }
              />
            )
          ) : (
            !work.error && <p className="muted">正在读取工作…</p>
          )}
          {work.data && (
            <Pagination
              page={work.page}
              hasNext={!!work.data.nextCursor}
              previous={work.previous}
              next={work.next}
            />
          )}
        </>
      )}
      {tab === 'messages' && (
        <div className="raw-messages">
          {messages.data?.items.map((m) => (
            <MessageCard key={m.id} message={m} onChange={messages.refresh} />
          ))}
          {nextCursor && (
            <button disabled={messages.loading} onClick={messages.loadMore}>
              加载更早上报
            </button>
          )}
          {!messages.data?.items.length && (
            <Empty title="尚未上报">上报会在员工发送成功后显示。</Empty>
          )}
        </div>
      )}
      {tab === 'reports' && (
        <>
          <div className="toolbar member-report-toolbar">
            <select
              aria-label="报告类型"
              value={kind}
              onChange={(e) =>
                setParams({ tab, kind: e.target.value }, { replace: true, state: location.state })
              }
            >
              <option value="daily">日报</option>
              <option value="weekly">周报</option>
            </select>
          </div>
          <div className="record-list">
            {reports.data?.items.map((r) => (
              <div className="record-row" key={r.id}>
                <Link
                  className="record-main report-entry-link"
                  to={`/reports/${r.id}`}
                  state={detailState(location)}
                >
                  <div className="record-main">
                    <h3>
                      {r.period}
                      {r.kind === 'weekly' ? ` — ${r.periodEnd}` : ''}
                    </h3>
                    <small>
                      已提交第 {r.publishedRevision} 版 · {dateLabel(r.updatedAt)}
                    </small>
                  </div>
                  <ChevronRight size={18} />
                </Link>
                <ReportActions report={r} onDeleted={reports.refresh} />
              </div>
            ))}
          </div>
          {!reports.data?.items.length && (
            <Empty title="尚未提交报告">员工未提交的草稿仅本人可见。</Empty>
          )}
        </>
      )}
    </div>
  )
}
