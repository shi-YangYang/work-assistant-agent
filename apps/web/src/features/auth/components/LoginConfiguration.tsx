import layoutStyles from '../../../styles/layout.module.css'
import utilitiesStyles from '../../../styles/utilities.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import loginConfigurationStyles from '../styles/login-settings.module.css'
import type { DingTalkConfiguration } from '@paa/api-contracts'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { FormField } from '@web/components/FormField'
import { Modal } from '@web/components/Modal'
import { PanelSection } from '@web/components/PanelSection'
import { saveDingTalkConfiguration } from '@web/features/auth/api/requests'
import { useDingTalkRedirect } from '@web/features/auth/hooks/useDingTalkRedirect'
import { loginConfigurationErrors } from '@web/features/auth/utils/login-configuration'
import { copyText } from '@web/lib/diagnostics'
import { dateLabel } from '@web/utils/date'
import { useState } from 'react'
import { useBlocker } from 'react-router'

export function LoginConfiguration({
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
  const [attempted, setAttempted] = useState(false)
  const fieldErrors = attempted
    ? loginConfigurationErrors({ corpId, clientId, secret }, value.hasSecret)
    : { corpId: '', clientId: '', secret: '' }
  const redirect = useDingTalkRedirect()
  const dirty = corpId !== value.corpId || clientId !== value.clientId || !!secret
  const blocker = useBlocker(dirty)
  const save = async (enabled: boolean) => {
    setAttempted(true)
    if (
      Object.values(loginConfigurationErrors({ corpId, clientId, secret }, value.hasSecret)).some(
        Boolean,
      )
    )
      return
    setBusy(true)
    setError('')
    try {
      await saveDingTalkConfiguration({
        corpId: corpId.trim(),
        clientId: clientId.trim(),
        secret,
        enabled,
        expectedRevision: value.revision,
      })
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
      <div className={layoutStyles['sectioned-panel']}>
        <PanelSection
          bodyClassName={loginConfigurationStyles['settings-section-body']}
          title="钉钉企业内部应用"
          status={value.hasSecret ? '已配置凭证' : '待配置'}
          defaultOpen
        >
          <form
            noValidate
            onSubmit={(event) => {
              event.preventDefault()
              void save(value.enabled)
            }}
          >
            <p className={utilitiesStyles['muted']}>
              先保存凭证，再验证授权和启用入口。新用户验证通过后会自动创建员工账号。
            </p>
            <div className={loginConfigurationStyles['credentials-fields']}>
              <FormField
                label="企业 CorpId"
                value={corpId}
                onChange={(event) => setCorpId(event.target.value)}
                required
                maxLength={128}
                error={fieldErrors.corpId}
                autoComplete="off"
              />
              <FormField
                label="Client ID / AppKey"
                value={clientId}
                onChange={(event) => setClientId(event.target.value)}
                required
                maxLength={128}
                error={fieldErrors.clientId}
                autoComplete="off"
              />
              <div className={layoutStyles['full-field']}>
                <FormField
                  label={
                    value.hasSecret
                      ? '替换 Client Secret / AppSecret（留空保留）'
                      : 'Client Secret / AppSecret'
                  }
                  type="password"
                  value={secret}
                  onChange={(event) => setSecret(event.target.value)}
                  required={!value.hasSecret}
                  maxLength={512}
                  error={fieldErrors.secret}
                  autoComplete="new-password"
                />
              </div>
            </div>
            <small>{value.hasSecret ? 'Secret 已加密保存，不会回显。' : '尚未配置 Secret。'}</small>
            <div
              className={`${layoutStyles['form-actions']} ${loginConfigurationStyles['slot-form-actions']}`}
            >
              <BusyButton busy={busy} className={controlsStyles['primary']}>
                保存配置
              </BusyButton>
            </div>
          </form>
        </PanelSection>
        <PanelSection
          bodyClassName={loginConfigurationStyles['settings-section-body']}
          title="授权与入口"
          status={value.enabled ? '已启用' : '未启用'}
          defaultOpen
        >
          <p>入口：{value.enabled ? '已启用' : '已关闭'}</p>
          <p>
            {value.verifiedAt
              ? `上次真实授权验证成功：${dateLabel(value.verifiedAt)}`
              : '配置尚未通过钉钉授权验证。'}
          </p>
          {dirty && <p className={utilitiesStyles['muted']}>请先保存修改，再验证或切换入口。</p>}
          <div
            className={`${layoutStyles['form-actions']} ${loginConfigurationStyles['slot-form-actions']}`}
          >
            <BusyButton
              type="button"
              busy={redirect.busy}
              disabled={busy || dirty || !value.hasSecret}
              onClick={() => redirect.launch('probe')}
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
        <PanelSection
          bodyClassName={loginConfigurationStyles['settings-section-body']}
          title="钉钉后台配置"
          status="回调地址与权限"
        >
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
          <p className={utilitiesStyles['muted']}>
            登记完整回调地址，开通 open_app_api_base、Contact.User.Read 和 qyapi_get_member
            权限并发布应用。请将通讯录授权范围设为允许登录的员工，并与应用可使用范围保持一致。
          </p>
          <p className={utilitiesStyles['muted']}>
            每次钉钉登录都会重新核验成员。本地密码和已登录会话的访问回收，需要在成员管理中停用账号。
          </p>
        </PanelSection>
      </div>
      {blocker.state === 'blocked' && (
        <Modal title="放弃未保存的登录配置？" onClose={() => blocker.reset()}>
          <p>更改尚未保存。</p>
          <div
            className={`${layoutStyles['form-actions']} ${loginConfigurationStyles['slot-form-actions']}`}
          >
            <button onClick={() => blocker.reset()}>继续编辑</button>
            <button onClick={() => blocker.proceed()}>放弃更改</button>
          </div>
        </Modal>
      )}
    </>
  )
}
