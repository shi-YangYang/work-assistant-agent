import { useContext, useEffect, useState, useSyncExternalStore } from 'react'
import { Link, useBlocker, useLocation, useNavigate } from 'react-router'
import type {
  DingTalkAccount,
  DingTalkConfiguration,
  LoginProviders,
  Member,
} from '@paa/api-contracts'
import { api, dateLabel, useResource, write } from './api'
import { copyText } from './diagnostics'
import { BusyButton, ErrorNotice, Modal, PanelSection } from './ui'
import { Workspace, type DraftStore } from './workspace'
import type { SessionDrafts } from './session-drafts'
import { dingtalkDraftSummary, dingtalkResult, officialDingTalkUrl } from './dingtalk-flow'
import dingtalkIcon from './assets/dingtalk.svg'

export function DingTalkResult() {
  const location = useLocation()
  const navigate = useNavigate()
  const [result] = useState(() => dingtalkResult(location.search))
  useEffect(() => {
    const query = new URLSearchParams(location.search)
    if (!query.has('dingtalk')) return
    for (const key of ['dingtalk', 'reason', 'requestId']) query.delete(key)
    void navigate({ pathname: location.pathname, search: query.toString() }, { replace: true })
  }, [location.pathname, location.search, navigate])
  if (!result) return null
  const message =
    location.pathname === '/settings/login' && !result.failed
      ? '真实钉钉授权验证成功。入口是否开放仍由启用开关控制。'
      : result.message
  return (
    <div
      className={`notice${result.failed ? ' error' : ''}`}
      role={result.failed ? 'alert' : 'status'}
    >
      <span>{message}</span>
      {result.requestId && <small>请求编号：{result.requestId}</small>}
    </div>
  )
}

function useDingTalkRedirect(drafts?: DraftStore) {
  const workspace = useContext(Workspace)
  const [pending, setPending] = useState<{ path: string; body: unknown } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  const [copied, setCopied] = useState('')
  const summary = dingtalkDraftSummary(drafts ?? workspace?.drafts ?? {})
  const proceed = async (path: string, body: unknown) => {
    setBusy(true)
    setError('')
    try {
      const result = await write<{ url: string }>(path, body)
      window.location.assign(officialDingTalkUrl(result.url))
    } catch (e) {
      setError(e as Error)
    } finally {
      setBusy(false)
    }
  }
  const launch = (path: string, body: unknown = {}) => {
    if (summary.hasDrafts) setPending({ path, body })
    else void proceed(path, body)
  }
  const guard = (
    <>
      {!pending && <ErrorNotice>{error}</ErrorNotice>}
      {pending && (
        <Modal title="前往钉钉前保留草稿" onClose={() => setPending(null)}>
          <p>
            当前还有未发送或未保存的内容。离开后这些内容会丢失；你可以取消并返回密码登录，或先复制文字再继续。
          </p>
          {summary.files > 0 && <p>还有 {summary.files} 个附件；离开后需要重新选择附件。</p>}
          {summary.text && (
            <textarea aria-label="待保留的聊天文字" readOnly value={summary.text} rows={5} />
          )}
          {copied && <p role="status">{copied}</p>}
          <ErrorNotice retry={busy ? undefined : () => void proceed(pending.path, pending.body)}>
            {error}
          </ErrorNotice>
          <div className="form-actions">
            <button type="button" onClick={() => setPending(null)}>
              取消并返回
            </button>
            {summary.text && (
              <button
                type="button"
                onClick={() =>
                  void copyText(summary.text).then(
                    () => setCopied('文字已复制'),
                    () => setCopied('复制失败，请手动选择上方文字。'),
                  )
                }
              >
                复制文字
              </button>
            )}
            <BusyButton
              type="button"
              busy={busy}
              onClick={() => void proceed(pending.path, pending.body)}
            >
              确认离开并前往钉钉
            </BusyButton>
          </div>
        </Modal>
      )}
    </>
  )
  return { launch, busy, guard }
}

export function DingTalkLogin({ vault }: { vault: SessionDrafts }) {
  const drafts = useSyncExternalStore(vault.subscribe, vault.getSnapshot)
  const [enabled, setEnabled] = useState(false)
  const redirect = useDingTalkRedirect(drafts)
  useEffect(() => {
    const controller = new AbortController()
    void api<LoginProviders>('/auth/providers', { signal: controller.signal }).then(
      (providers) => {
        if (!controller.signal.aborted) setEnabled(providers.dingtalk)
      },
      () => {
        /* Password login remains available when discovery is offline. */
      },
    )
    return () => controller.abort()
  }, [])
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (!dingtalkDraftSummary(drafts).hasDrafts) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [drafts])
  if (!enabled) return null
  return (
    <div className="dingtalk-login">
      <BusyButton
        type="button"
        busy={redirect.busy}
        onClick={() => redirect.launch('/auth/dingtalk/start')}
      >
        <img src={dingtalkIcon} width={20} height={20} alt="" aria-hidden="true" />
        使用钉钉登录
      </BusyButton>
      <div className="login-divider">或使用账号登录</div>
      {redirect.guard}
    </div>
  )
}

export function LoginMethods() {
  const resource = useResource<DingTalkConfiguration>('/settings/login/dingtalk')
  const [notice, setNotice] = useState('')
  return (
    <div className="settings-page login-methods">
      <h2>登录方式</h2>
      <p className="muted">账号密码登录始终可用。钉钉按本公司的通讯录授权范围核验成员。</p>
      <DingTalkResult />
      {notice && <p role="status">{notice}</p>}
      <ErrorNotice retry={resource.refresh}>{resource.error}</ErrorNotice>
      {resource.data ? (
        <LoginConfiguration
          key={resource.data.revision}
          value={resource.data}
          saved={(message) => {
            setNotice(message)
            resource.refresh()
          }}
        />
      ) : (
        !resource.error && <p>正在读取登录配置…</p>
      )}
    </div>
  )
}

function LoginConfiguration({
  value,
  saved,
}: {
  value: DingTalkConfiguration
  saved: (message: string) => void
}) {
  const [corpId, setCorpId] = useState(value.corpId)
  const [clientId, setClientId] = useState(value.clientId)
  const [secret, setSecret] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  const [copied, setCopied] = useState('')
  const redirect = useDingTalkRedirect()
  const dirty = corpId !== value.corpId || clientId !== value.clientId || !!secret
  const blocker = useBlocker(dirty)
  const save = async (enabled: boolean) => {
    setBusy(true)
    setError('')
    try {
      await write(
        '/settings/login/dingtalk',
        {
          corpId: corpId.trim(),
          clientId: clientId.trim(),
          secret,
          enabled,
          expectedRevision: value.revision,
        },
        'PUT',
      )
      setSecret('')
      saved(
        enabled !== value.enabled
          ? enabled
            ? '钉钉登录入口已启用。'
            : '钉钉登录入口已关闭。'
          : '配置已保存。请使用“验证授权”检查真实登录。',
      )
    } catch (e) {
      setError(e as Error)
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <ErrorNotice>{error}</ErrorNotice>
      <div className="sectioned-panel">
        <PanelSection
          title="钉钉企业内部应用"
          status={value.hasSecret ? '已配置凭证' : '待配置'}
          defaultOpen
        >
          <form
            onSubmit={(event) => {
              event.preventDefault()
              void save(value.enabled)
            }}
          >
            <p className="muted">
              先保存凭证，再验证授权和启用入口。新用户验证通过后会自动创建员工账号。
            </p>
            <div className="credentials-fields">
              <label>
                企业 CorpId
                <input
                  value={corpId}
                  onChange={(event) => setCorpId(event.target.value)}
                  required
                  maxLength={128}
                  autoComplete="off"
                />
              </label>
              <label>
                Client ID / AppKey
                <input
                  value={clientId}
                  onChange={(event) => setClientId(event.target.value)}
                  required
                  maxLength={128}
                  autoComplete="off"
                />
              </label>
              <label className="full-field">
                {value.hasSecret
                  ? '替换 Client Secret / AppSecret（留空保留）'
                  : 'Client Secret / AppSecret'}
                <input
                  type="password"
                  value={secret}
                  onChange={(event) => setSecret(event.target.value)}
                  required={!value.hasSecret}
                  maxLength={512}
                  autoComplete="new-password"
                />
              </label>
            </div>
            <small>{value.hasSecret ? 'Secret 已加密保存，不会回显。' : '尚未配置 Secret。'}</small>
            <div className="form-actions">
              <BusyButton busy={busy} className="primary">
                保存配置
              </BusyButton>
            </div>
          </form>
        </PanelSection>
        <PanelSection title="授权与入口" status={value.enabled ? '已启用' : '未启用'} defaultOpen>
          <p>入口：{value.enabled ? '已启用' : '已关闭'}</p>
          <p>
            {value.verifiedAt
              ? `上次真实授权验证成功：${dateLabel(value.verifiedAt)}`
              : '配置尚未通过钉钉授权验证。'}
          </p>
          {dirty && <p className="muted">请先保存修改，再验证或切换入口。</p>}
          <div className="form-actions">
            <BusyButton
              type="button"
              busy={redirect.busy}
              disabled={busy || dirty || !value.hasSecret}
              onClick={() => redirect.launch('/settings/login/dingtalk/probe')}
            >
              验证授权
            </BusyButton>
            <BusyButton
              type="button"
              busy={busy}
              disabled={dirty || !value.hasSecret}
              onClick={() => void save(!value.enabled)}
            >
              {value.enabled ? '关闭钉钉登录' : '启用钉钉登录'}
            </BusyButton>
          </div>
          {redirect.guard}
        </PanelSection>
        <PanelSection title="钉钉后台配置" status="回调地址与权限">
          <label>
            回调地址
            <input readOnly value={value.callbackUrl} />
          </label>
          <button
            type="button"
            onClick={() =>
              void copyText(value.callbackUrl).then(
                () => setCopied('回调地址已复制'),
                () => setCopied('请手动选择上方地址复制。'),
              )
            }
          >
            复制回调地址
          </button>
          {copied && <p role="status">{copied}</p>}
          <p className="muted">
            登记完整回调地址，开通 open_app_api_base、Contact.User.Read 和 qyapi_get_member
            权限并发布应用。请将通讯录授权范围设为允许登录的员工，并与应用可使用范围保持一致。
          </p>
          <p className="muted">
            每次钉钉登录都会重新核验成员。本地密码和已登录会话的访问回收，需要在成员管理中停用账号。
          </p>
        </PanelSection>
      </div>
      {blocker.state === 'blocked' && (
        <Modal title="放弃未保存的登录配置？" onClose={() => blocker.reset()}>
          <p>更改尚未保存。</p>
          <div className="form-actions">
            <button onClick={() => blocker.reset()}>继续编辑</button>
            <button onClick={() => blocker.proceed()}>放弃更改</button>
          </div>
        </Modal>
      )}
    </>
  )
}

export function DingTalkAccountPage({
  onLogout,
  force = false,
  member,
}: {
  onLogout: () => void
  force?: boolean
  member?: Member
}) {
  const account = useResource<DingTalkAccount>('/auth/dingtalk/account')
  const redirect = useDingTalkRedirect()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  const [copied, setCopied] = useState('')
  const [useDingTalk, setUseDingTalk] = useState(false)
  const [localPassword, setLocalPassword] = useState('')
  const hasPassword = account.data?.hasPassword ?? member?.hasPassword ?? true
  const verified = !!account.data?.passwordVerified
  const viaDingTalk = !hasPassword || useDingTalk || verified
  return (
    <div className={force ? 'password-reset' : 'settings-page account-page'}>
      {!force && (
        <>
          <div className="row-between account-heading">
            <h2>账户</h2>
            <Link to="/settings/support">问题反馈与处理结果</Link>
          </div>
        </>
      )}
      <DingTalkResult />
      <ErrorNotice retry={account.refresh}>{error || account.error}</ErrorNotice>
      <div className="sectioned-panel">
        <PanelSection
          title="账号信息"
          status={member?.role === 'admin' ? '管理员' : '用户'}
          defaultOpen
        >
          {!force && (
            <div className="account-summary">
              <span className="avatar">{member?.name.slice(0, 1)}</span>
              <strong>{member?.name}</strong>
            </div>
          )}
          <div className="account-username">
            <label>
              登录账号
              <input readOnly value={member?.username ?? ''} />
            </label>
            <button
              type="button"
              onClick={() =>
                void copyText(member?.username ?? '').then(
                  () => setCopied('登录账号已复制'),
                  () => setCopied('请手动选择登录账号复制。'),
                )
              }
            >
              复制账号
            </button>
          </div>
          {copied && <p role="status">{copied}</p>}
          <p>本地密码：{hasPassword ? '已设置密码' : '未设置密码'}</p>
          {account.data && <p>钉钉：{account.data.bound ? '已绑定' : '未绑定'}</p>}
        </PanelSection>
        <PanelSection
          title={hasPassword ? '修改或重置密码' : '设置本地密码'}
          status={hasPassword ? '已设置密码' : '未设置密码'}
          defaultOpen={force || !hasPassword || verified}
        >
          <form
            className="password-form"
            onSubmit={async (event) => {
              event.preventDefault()
              const data = new FormData(event.currentTarget)
              if (data.get('new') !== data.get('confirm')) {
                setError('两次新密码不一致')
                return
              }
              setBusy(true)
              setError('')
              try {
                await write('/auth/password', {
                  currentPassword: viaDingTalk ? '' : data.get('current'),
                  newPassword: data.get('new'),
                  useDingTalk: viaDingTalk,
                })
                onLogout()
              } catch (e) {
                setError(e as Error)
                account.refresh()
              } finally {
                setBusy(false)
              }
            }}
          >
            {hasPassword && !verified && (
              <label>
                当前密码
                <input
                  name="current"
                  type="password"
                  required={!viaDingTalk}
                  disabled={viaDingTalk}
                  autoComplete="current-password"
                  maxLength={128}
                />
              </label>
            )}
            {account.data?.bound && account.data.available && (
              <>
                {hasPassword && !verified && (
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={useDingTalk}
                      onChange={(event) => setUseDingTalk(event.target.checked)}
                    />
                    忘记密码，使用钉钉重新验证
                  </label>
                )}
                {viaDingTalk && (
                  <p>
                    {verified
                      ? '已验证本人钉钉身份，请在 5 分钟内设置新密码。'
                      : '请先重新验证已绑定的本人钉钉身份，再输入新密码。'}
                  </p>
                )}
                {viaDingTalk && !verified && (
                  <BusyButton
                    type="button"
                    busy={redirect.busy}
                    onClick={() => redirect.launch('/auth/dingtalk/account/reauth')}
                  >
                    重新验证钉钉身份
                  </BusyButton>
                )}
              </>
            )}
            {!hasPassword && !account.data?.available && (
              <p>钉钉登录当前不可用，请联系管理员恢复入口后验证身份，或由管理员重置临时密码。</p>
            )}
            <label>
              新密码
              <input
                name="new"
                type="password"
                autoComplete="new-password"
                required
                minLength={12}
                maxLength={128}
                disabled={viaDingTalk && !verified}
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
                disabled={viaDingTalk && !verified}
              />
            </label>
            <small>至少 12 位。保存后所有已登录设备均需重新登录。</small>
            <div className="form-actions">
              <BusyButton busy={busy} className="primary" disabled={viaDingTalk && !verified}>
                保存密码并重新登录
              </BusyButton>
            </div>
          </form>
        </PanelSection>
        {!force && account.data && (
          <PanelSection title="钉钉账号关联" status={account.data.bound ? '已绑定' : '未绑定'}>
            {!account.data.bound ? (
              <>
                <p>验证当前本地密码后绑定，保留现有账号和业务数据。</p>
                <label>
                  当前本地密码
                  <input
                    type="password"
                    autoComplete="current-password"
                    value={localPassword}
                    onChange={(event) => setLocalPassword(event.target.value)}
                    maxLength={128}
                  />
                </label>
                <BusyButton
                  busy={redirect.busy}
                  disabled={!account.data.available || !localPassword}
                  onClick={() =>
                    redirect.launch('/auth/dingtalk/account/bind', {
                      currentPassword: localPassword,
                    })
                  }
                >
                  验证密码并绑定钉钉
                </BusyButton>
                {!account.data.available && <p className="muted">管理员尚未开启钉钉登录。</p>}
              </>
            ) : (
              <>
                <p>更换钉钉身份时，先验证并解绑，再使用本地密码登录后绑定新身份。</p>
                {!hasPassword ? (
                  <p>钉钉是当前唯一登录方式。请先设置本地密码后再解绑。</p>
                ) : (
                  <>
                    <label>
                      解绑前验证本地密码
                      <input
                        type="password"
                        autoComplete="current-password"
                        value={localPassword}
                        onChange={(event) => setLocalPassword(event.target.value)}
                        maxLength={128}
                        disabled={verified}
                      />
                    </label>
                    <BusyButton
                      busy={busy}
                      disabled={!localPassword && !verified}
                      className="danger"
                      onClick={async () => {
                        if (!window.confirm('解绑钉钉并退出所有设备？之后请用本地密码登录。'))
                          return
                        setBusy(true)
                        setError('')
                        try {
                          await write('/auth/dingtalk/account/unbind', {
                            currentPassword: localPassword,
                            useDingTalk: verified,
                          })
                          onLogout()
                        } catch (e) {
                          setError(e as Error)
                        } finally {
                          setBusy(false)
                        }
                      }}
                    >
                      解绑并重新登录
                    </BusyButton>
                  </>
                )}
              </>
            )}
          </PanelSection>
        )}
      </div>
      {redirect.guard}
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
