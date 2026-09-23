import layoutStyles from '../../../styles/layout.module.css'
import utilitiesStyles from '../../../styles/utilities.module.css'
import loginConfigurationStyles from '../styles/login-settings.module.css'
import type { DingTalkConfiguration } from '@paa/api-contracts'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { dingTalkConfigurationPath } from '@web/features/auth/api/requests'
import { DingTalkResult } from '@web/features/auth/components/DingTalkResult'
import { LoginConfiguration } from '@web/features/auth/components/LoginConfiguration'
import { useResource } from '@web/hooks/useResource'
import { useState } from 'react'

export function LoginMethods() {
  const resource = useResource<DingTalkConfiguration>(dingTalkConfigurationPath())
  const [notice, setNotice] = useState('')
  return (
    <div
      className={`${layoutStyles['settings-page']} ${loginConfigurationStyles['login-methods']}`}
    >
      <h2>登录方式</h2>
      <p className={utilitiesStyles['muted']}>
        账号密码登录始终可用。钉钉按本公司的通讯录授权范围核验成员。
      </p>
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
