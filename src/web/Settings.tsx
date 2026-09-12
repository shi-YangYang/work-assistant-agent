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
} from '../shared/company-contracts'
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
  const [error, setError] = useState('')
  return (
    <div className={force ? 'password-reset' : 'settings-page account-page'}>
      {!force && (
        <>
          <h2>账户</h2>
          <div className="account-summary">
            <span className="avatar">{member?.name.slice(0, 1)}</span>
            <div>
              <h3>{member?.name}</h3>
              <p className="muted">
                {member?.username} · {member?.role === 'admin' ? '老板／管理员' : '员工'}
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
            setError((e as Error).message)
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
              setError((e as Error).message)
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
  const [failure, setFailure] = useState('')
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
          <p className="muted">公司时区：{value.timezone}</p>
          {(['daily', 'weekly'] as const).map((kind) => (
            <section className="panel schedule-panel" key={kind}>
              <div className="row-between">
                <h3>{kind === 'daily' ? '日报' : '周报'}</h3>
                <span className="status">{value[kind].enabled ? '自动生成' : '未启用'}</span>
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
              setFailure((e as Error).message)
            } finally {
              setBusy(false)
            }
          }}
        >
          <label className="timezone-field">
            公司时区
            <input
              value={value.timezone}
              disabled={!canEdit}
              list="timezones"
              onChange={(e) => setDraft('rules', { ...value, timezone: e.target.value })}
            />
            <datalist id="timezones">
              <option>Asia/Shanghai</option>
              <option>Asia/Hong_Kong</option>
              <option>Asia/Tokyo</option>
              <option>Europe/London</option>
              <option>America/New_York</option>
              <option>UTC</option>
            </datalist>
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
                  自动生成
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
                  <input
                    type="time"
                    required={value[kind].enabled}
                    value={value[kind].generateTime}
                    onChange={(e) => update(kind, { ...value[kind], generateTime: e.target.value })}
                  />
                </label>
                <label>
                  提交截止时间
                  <input
                    type="time"
                    required={value[kind].enabled}
                    value={value[kind].deadline}
                    onChange={(e) => update(kind, { ...value[kind], deadline: e.target.value })}
                  />
                </label>
              </div>
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
                  <p>公司时区：{latest.timezone}</p>
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
  const [failure, setFailure] = useState('')
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
      setFailure((e as Error).message)
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
                {member.username} · {member.role === 'admin' ? '老板／管理员' : '员工'} ·{' '}
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
                    role: form.get('role'),
                    password: form.get('password'),
                  })
                setCreate(false)
                setReset(null)
                refresh()
                notify('已保存，请将账号与临时密码交给成员；首次登录需修改')
              } catch (e) {
                setFailure((e as Error).message)
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
                <label>
                  角色
                  <select name="role">
                    <option value="employee">员工</option>
                    <option value="admin">老板／管理员</option>
                  </select>
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
  const filter = params.get('q') ?? ''
  const status = params.get('status') ?? ''
  const path = `/team?${new URLSearchParams({ status, ...(params.get('start') ? { start: params.get('start')! } : {}), ...(params.get('end') ? { end: params.get('end')! } : {}) })}`
  const { data, error, refresh } = useResource<Team>(path, 30000)
  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }
  const items =
    data?.items.filter(
      (item) => item.member.name.includes(filter) && (!status || item.work.length),
    ) ?? []
  return (
    <div className="page">
      <div className="page-heading">
        <div>
          <h2>团队看板</h2>
          <p>{data ? `更新于 ${dateLabel(data.updatedAt)}` : '查看员工已确认的进展与上报'}</p>
        </div>
        <button onClick={refresh}>
          <RefreshCw size={16} />
          刷新
        </button>
      </div>
      <ErrorNotice retry={refresh}>{error}</ErrorNotice>
      <div className="metrics">
        <div>
          <small>已上报员工</small>
          <strong>
            {data?.items.filter((i) => i.lastMessageAt).length ?? 0}
            <span> / {data?.items.length ?? 0}</span>
          </strong>
        </div>
        <div>
          <small>有阻碍的工作</small>
          <strong>
            {data?.items.flatMap((i) => i.work).filter((w) => w.status === 'blocked' || w.blocker)
              .length ?? 0}
          </strong>
        </div>
        <div>
          <small>已提交报告</small>
          <strong>{data?.items.reduce((n, i) => n + i.reportCount, 0) ?? 0}</strong>
        </div>
      </div>
      <div className="filters team-filters">
        <input
          aria-label="搜索员工"
          placeholder="搜索员工"
          value={filter}
          onChange={(e) => update('q', e.target.value)}
        />
        <select
          aria-label="进展状态"
          value={status}
          onChange={(e) => update('status', e.target.value)}
        >
          <option value="">全部状态</option>
          <option value="in_progress">进行中</option>
          <option value="blocked">有阻碍</option>
          <option value="done">已完成</option>
        </select>
        <div className="team-date-range" role="group" aria-label="进展更新日期范围">
          <label>
            开始日期
            <input
              type="date"
              max={params.get('end') || undefined}
              value={params.get('start') ?? ''}
              onChange={(e) => update('start', e.target.value)}
            />
          </label>
          <span aria-hidden="true">至</span>
          <label>
            结束日期
            <input
              type="date"
              min={params.get('start') || undefined}
              value={params.get('end') ?? ''}
              onChange={(e) => update('end', e.target.value)}
            />
          </label>
        </div>
        {(params.get('start') || params.get('end')) && (
          <button
            onClick={() => {
              const next = new URLSearchParams(params)
              next.delete('start')
              next.delete('end')
              setParams(next)
            }}
          >
            清除日期
          </button>
        )}
      </div>
      {items.length ? (
        <div className="record-list">
          {items.map((item) => (
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
                <p className="record-summary">{item.work[0]?.summary ?? '尚无已确认进展'}</p>
              </div>
              <small className="record-updated">
                {item.lastMessageAt
                  ? `最近上报 ${dateLabel(item.lastMessageAt)}`
                  : '尚未上报，不代表未开展工作'}
              </small>
              {item.work.some((w) => w.blocker || w.status === 'blocked') && (
                <span className="status blocked">有阻碍</span>
              )}
              <ChevronRight size={18} />
            </Link>
          ))}
        </div>
      ) : (
        <Empty title="没有符合条件的员工">可调整筛选条件，或先添加员工账号。</Empty>
      )}
      <Link className="mobile-only" to="/members">
        管理成员
      </Link>
    </div>
  )
}
export function TeamMemberPage() {
  const location = useLocation()
  const { id } = useParams()
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') ?? 'work'
  const kind = params.get('kind') ?? 'daily'
  const work = useResource<Page<Work> & { member: Member }>(`/team/members/${id}/work`, 30000)
  const messages = useResource<Page<WorkMessage>>(
    tab === 'messages' ? `/team/members/${id}/messages` : null,
    30000,
  )
  const reports = useResource<Page<Report>>(
    tab === 'reports' ? `/team/members/${id}/reports?kind=${kind}` : null,
    30000,
  )
  const [older, setOlder] = useState<WorkMessage[]>([])
  const [cursor, setCursor] = useState<string | null | undefined>(undefined)
  const { notify } = useWorkspace()
  const nextCursor = cursor === undefined ? messages.data?.nextCursor : cursor
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
      {tab === 'work' &&
        (work.data?.items.length ? (
          <WorkList items={work.data.items} refresh={work.refresh} />
        ) : (
          <Empty title="尚无已确认进展" />
        ))}
      {tab === 'messages' && (
        <div className="raw-messages">
          {[...(messages.data?.items ?? []), ...older]
            .filter((m, i, all) => all.findIndex((x) => x.id === m.id) === i)
            .map((m) => (
              <MessageCard key={m.id} message={m} onChange={messages.refresh} />
            ))}
          {nextCursor && (
            <button
              onClick={async () => {
                try {
                  const page = await api<Page<WorkMessage>>(
                    `/team/members/${id}/messages?cursor=${nextCursor}`,
                  )
                  setOlder([...older, ...page.items])
                  setCursor(page.nextCursor)
                } catch (e) {
                  notify((e as Error).message)
                }
              }}
            >
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
              <Link
                key={r.id}
                className="record-row"
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
