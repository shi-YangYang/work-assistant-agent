import type { DingTalkAccount, Member } from '@paa/api-contracts'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { PanelSection } from '@web/components/PanelSection'
import { logout } from '@web/features/auth/api/requests'
import { DingTalkResult } from '@web/features/auth/components/DingTalkResult'
import { useDingTalkRedirect } from '@web/features/auth/hooks/useDingTalkRedirect'
import {
  changePassword,
  dingTalkAccountPath,
  unbindDingTalk,
} from '@web/features/settings/api/requests'
import { useResource } from '@web/hooks/useResource'
import { copyText } from '@web/lib/diagnostics'
import { useState } from 'react'
import { Link } from 'react-router'

export function DingTalkAccountPage({
  onLogout,
  force = false,
  member,
}: {
  onLogout: () => void
  force?: boolean
  member?: Member
}) {
  const account = useResource<DingTalkAccount>(dingTalkAccountPath())
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
                await changePassword({
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
                    onClick={() => redirect.launch('reauthenticate')}
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
                    redirect.launch('bind', {
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
                          await unbindDingTalk({
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
              await logout({})
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
