import layoutStyles from '../../../styles/layout.module.css'
import utilitiesStyles from '../../../styles/utilities.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import styles from './AccountPage.module.css'
import { inputRules, type DingTalkAccount, type Member } from '@paa/api-contracts'
import { ApiError } from '@web/api/client'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { FormField } from '@web/components/FormField'
import { PanelSection } from '@web/components/PanelSection'
import { logout } from '@web/features/auth/api/requests'
import { DingTalkResult } from '@web/features/auth/components/DingTalkResult'
import { useDingTalkRedirect } from '@web/features/auth/hooks/useDingTalkRedirect'
import { dingTalkAccountPath, unbindDingTalk } from '@web/features/settings/api/requests'
import { PasswordForm } from '@web/features/settings/components/PasswordForm'
import { useResource } from '@web/hooks/useResource'
import { copyText } from '@web/lib/diagnostics'
import { useState, type ChangeEvent } from 'react'
import { Link } from 'react-router'

export function DingTalkAccountPage({
  onLogout,
  member,
}: {
  onLogout: () => void
  member?: Member
}) {
  const account = useResource<DingTalkAccount>(dingTalkAccountPath())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  const [copied, setCopied] = useState('')
  const [localPassword, setLocalPassword] = useState('')
  const [localPasswordError, setLocalPasswordError] = useState('')
  const redirect = useDingTalkRedirect(undefined, passwordFailure)
  const hasPassword = account.data?.hasPassword ?? member?.hasPassword ?? true
  const verified = !!account.data?.passwordVerified
  const passwordMax = inputRules.member.password.max

  function passwordFailure(failure: unknown) {
    if (!(failure instanceof ApiError)) return false
    const message =
      failure.fieldErrors.currentPassword ||
      (failure.fields.includes('body.currentPassword') ? `当前密码不能超过 ${passwordMax} 位` : '')
    if (!message) return false
    setLocalPasswordError(message)
    return true
  }

  function validateLocalPassword() {
    const message = !localPassword
      ? '请输入当前本地密码'
      : [...localPassword].length > passwordMax
        ? `当前密码不能超过 ${passwordMax} 位`
        : ''
    setLocalPasswordError(message)
    return !message
  }

  const localPasswordInput = {
    type: 'password',
    autoComplete: 'current-password',
    value: localPassword,
    error: localPasswordError,
    readOnly: busy || redirect.busy,
    onChange: (event: ChangeEvent<HTMLInputElement>) => {
      const value = event.currentTarget.value
      setLocalPassword(value)
      if (localPasswordError)
        setLocalPasswordError(
          !value
            ? '请输入当前本地密码'
            : [...value].length > passwordMax
              ? `当前密码不能超过 ${passwordMax} 位`
              : '',
        )
    },
    onBlur: () => {
      if (!localPasswordError) validateLocalPassword()
    },
  }
  return (
    <div className={`${layoutStyles['settings-page']} ${styles['account-page']}`}>
      <div className={`${layoutStyles['row-between']} ${styles['account-heading']}`}>
        <h2>账户</h2>
        <Link to="/settings/support">问题反馈与处理结果</Link>
      </div>
      <DingTalkResult />
      <ErrorNotice retry={account.refresh}>{error || account.error}</ErrorNotice>
      <div className={layoutStyles['sectioned-panel']}>
        <PanelSection
          bodyClassName={styles['settings-section-body']}
          title="账号信息"
          status={member?.role === 'admin' ? '管理员' : '用户'}
          defaultOpen
        >
          <div className={styles['account-summary']}>
            <span className={layoutStyles['avatar']}>{member?.name.slice(0, 1)}</span>
            <strong>{member?.name}</strong>
          </div>
          <div className={styles['account-username']}>
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
          bodyClassName={styles['settings-section-body']}
          title={hasPassword ? '修改密码' : '设置本地密码'}
          status={hasPassword ? '已设置密码' : '未设置密码'}
          defaultOpen={!hasPassword || verified}
        >
          <PasswordForm
            account={account.data}
            hasPassword={hasPassword}
            redirect={redirect}
            onSaved={onLogout}
            onFailure={account.refresh}
          />
        </PanelSection>
        {account.data && (
          <PanelSection
            bodyClassName={styles['settings-section-body']}
            title="钉钉账号关联"
            status={account.data.bound ? '已绑定' : '未绑定'}
          >
            {!account.data.bound ? (
              <>
                <p>验证当前本地密码后绑定，保留现有账号和业务数据。</p>
                <FormField {...localPasswordInput} label="当前本地密码" required />
                <BusyButton
                  busy={redirect.busy}
                  disabled={!account.data.available || !localPassword}
                  onClick={() => {
                    if (!validateLocalPassword()) return
                    setError('')
                    redirect.launch('bind', { currentPassword: localPassword })
                  }}
                >
                  验证密码并绑定钉钉
                </BusyButton>
                {!account.data.available && (
                  <p className={utilitiesStyles['muted']}>管理员尚未开启钉钉登录。</p>
                )}
              </>
            ) : (
              <>
                <p>更换钉钉身份时，先验证并解绑，再使用本地密码登录后绑定新身份。</p>
                {!hasPassword ? (
                  <p>钉钉是当前唯一登录方式。请先设置本地密码后再解绑。</p>
                ) : (
                  <>
                    <FormField
                      {...localPasswordInput}
                      label="解绑前验证本地密码"
                      required={!verified}
                      disabled={verified}
                      error={verified ? undefined : localPasswordError}
                    />
                    <BusyButton
                      busy={busy}
                      disabled={!localPassword && !verified}
                      className={controlsStyles['danger']}
                      onClick={async () => {
                        if (!verified && !validateLocalPassword()) return
                        if (!window.confirm('解绑钉钉并退出所有设备？之后请用本地密码登录。'))
                          return
                        setBusy(true)
                        setError('')
                        try {
                          await unbindDingTalk({
                            currentPassword: verified ? '' : localPassword,
                            useDingTalk: verified,
                          })
                          onLogout()
                        } catch (e) {
                          if (!passwordFailure(e)) setError(e as Error)
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
      <button
        className={controlsStyles['danger']}
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
    </div>
  )
}
