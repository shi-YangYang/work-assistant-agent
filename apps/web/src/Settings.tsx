import { companyTimezones, timezoneLabel } from './timezones'
import { PanelSection, TimeField } from './ui'
import { useEffect, useState } from 'react'
import { UserPlus } from 'lucide-react'
import type { Member, Page, Rules, Schedule, Theme } from '@paa/api-contracts'
import { api, useResource, write } from './api'
import { useWorkspace } from './workspace'
import { ConflictRecovery, Actions, BusyButton, ErrorNotice, Modal } from './ui'

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
export { DingTalkAccountPage as AccountPage } from './DingTalk'

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
        <div className="sectioned-panel rule-summary">
          <div className="panel-intro muted">公司时区：{timezoneLabel(value.timezone)}</div>
          {(['daily', 'weekly'] as const).map((kind) => (
            <PanelSection
              key={kind}
              title={kind === 'daily' ? '日报' : '周报'}
              status={value[kind].enabled ? '已启用' : '未启用'}
              defaultOpen={value[kind].enabled}
            >
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
            </PanelSection>
          ))}
        </div>
      )}
      {value && canEdit && (
        <form
          className="sectioned-panel rules-form"
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
          <PanelSection title="时间设置" status={timezoneLabel(value.timezone)} defaultOpen>
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
          </PanelSection>
          {(['daily', 'weekly'] as const).map((kind) => (
            <PanelSection
              key={kind}
              title={kind === 'daily' ? '日报' : '周报'}
              status={
                value[kind].enabled
                  ? `${value[kind].generateTime} 生成 · ${value[kind].deadline} 截止`
                  : '未启用'
              }
              defaultOpen={kind === 'daily'}
            >
              <div className="schedule-panel">
                <label className="check">
                  <input
                    type="checkbox"
                    checked={value[kind].enabled}
                    onChange={(e) => update(kind, { ...value[kind], enabled: e.target.checked })}
                  />
                  启用汇报安排
                </label>
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
                      onChange={(e) =>
                        update(kind, { ...value[kind], reminders: e.target.checked })
                      }
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
              </div>
            </PanelSection>
          ))}
          <div className="panel-footer">
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

function DeleteMember({
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
              await write(`/members/${member.id}`, undefined, 'DELETE')
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
