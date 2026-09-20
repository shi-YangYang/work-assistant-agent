import dingtalkIcon from '@web/assets/dingtalk.svg'
import { BusyButton } from '@web/components/BusyButton'
import { readLoginProviders } from '@web/features/auth/api/requests'
import { useDingTalkRedirect } from '@web/features/auth/hooks/useDingTalkRedirect'
import { dingtalkDraftSummary } from '@web/features/auth/utils/dingtalk-flow'
import type { SessionDrafts } from '@web/lib/session-drafts'
import { useEffect, useState, useSyncExternalStore } from 'react'

export function DingTalkLogin({ vault }: { vault: SessionDrafts }) {
  const drafts = useSyncExternalStore(vault.subscribe, vault.getSnapshot)
  const [enabled, setEnabled] = useState(false)
  const redirect = useDingTalkRedirect(drafts)
  useEffect(() => {
    const controller = new AbortController()
    void readLoginProviders({ signal: controller.signal }).then(
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
      <BusyButton type="button" busy={redirect.busy} onClick={() => redirect.launch('login')}>
        <img src={dingtalkIcon} width={20} height={20} alt="" aria-hidden="true" />
        使用钉钉登录
      </BusyButton>
      <div className="login-divider">或使用账号登录</div>
      {redirect.guard}
    </div>
  )
}
