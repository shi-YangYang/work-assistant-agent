import { PageHeader } from '@web/components/layout/page-header/PageHeader'
import layoutStyles from '../../../../styles/layout.module.css'
import loginConfigurationStyles from '../../styles/login-settings.module.css'
import type { DingTalkConfiguration } from '@paa/api-contracts'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { dingTalkConfigurationPath } from '@web/features/auth/api/requests'
import { DingTalkResult } from '@web/features/auth/components/DingTalkResult'
import {
  LoginConfiguration,
  type LoginConfigurationTab,
} from '@web/features/auth/components/configuration/LoginConfiguration'
import { useResource } from '@web/hooks/useResource'
import { useState } from 'react'

export function LoginMethods() {
  const resource = useResource<DingTalkConfiguration>(dingTalkConfigurationPath())
  const [notice, setNotice] = useState('')
  const [tab, setTab] = useState<LoginConfigurationTab>('credentials')
  return (
    <div
      className={`${layoutStyles['settings-page']} ${layoutStyles['settings-form-page']} ${loginConfigurationStyles['login-methods']}`}
    >
      <PageHeader
        title="登录方式"
        description="账号密码登录始终可用。钉钉按本公司的通讯录授权范围核验成员。"
      />
      <DingTalkResult />
      {notice && <p role="status">{notice}</p>}
      <ErrorNotice retry={resource.refresh}>{resource.error}</ErrorNotice>
      {resource.data ? (
        <LoginConfiguration
          key={resource.data.revision}
          value={resource.data}
          tab={tab}
          selectTab={setTab}
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
