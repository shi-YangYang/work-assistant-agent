import loginStyles from '../styles/login-form.module.css'
import dingtalkIcon from '@web/assets/dingtalk.svg'
import { BusyButton } from '@web/components/BusyButton'
import { readLoginProviders } from '@web/features/auth/api/requests'
import { useDingTalkRedirect } from '@web/features/auth/hooks/useDingTalkRedirect'
import { dingtalkDraftSummary } from '@web/features/auth/utils/dingtalk-flow'
import type { SessionDrafts } from '@web/lib/session-drafts'
import { useEffect, useState, useSyncExternalStore } from 'react'

export function DingTalkLogin({
  vault,
  disabled,
  onBusyChange,
}: {
  vault: SessionDrafts
  disabled: boolean
  onBusyChange: (busy: boolean) => void
}) {
  const drafts = useSyncExternalStore(vault.subscribe, vault.getSnapshot)
  const [enabled, setEnabled] = useState(false)
  const redirect = useDingTalkRedirect(
    drafts,
    undefined,
    loginStyles['login-notice'],
    loginStyles['login-notice-actions'],
  )
  useEffect(() => onBusyChange(redirect.busy), [redirect.busy, onBusyChange])
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
    <div className={loginStyles['dingtalk-login']}>
      <div className={loginStyles['login-divider']}>或</div>
      <BusyButton
        type="button"
        busy={redirect.busy}
        disabled={disabled}
        onClick={() => redirect.launch('login')}
      >
        <img src={dingtalkIcon} width={20} height={20} alt="" aria-hidden="true" />
        使用钉钉登录
      </BusyButton>
      {redirect.guard}
    </div>
  )
}
