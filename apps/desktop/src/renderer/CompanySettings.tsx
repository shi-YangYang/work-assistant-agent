import { useEffect, useRef, useState } from 'react'
import { Building2, ExternalLink, Fingerprint, LogOut, RefreshCw, Trash2 } from 'lucide-react'
import type { CompanyRequest, CompanyStatus } from '../shared/company-contracts'

export const guestCompany: CompanyStatus = {
  serverUrl: '',
  session: 'guest',
  identity: null,
  busy: false,
  error: null,
  syncedAt: null,
  profileCount: 0,
  engine: null,
}
export function CompanySettings({
  status,
  onChange,
  visible,
}: {
  status: CompanyStatus
  visible: boolean
  onChange: (value: CompanyStatus) => void
}): React.JSX.Element {
  useEffect(() => {
    if (!visible) return
    let alive = true,
      reading = false
    const refresh = async (): Promise<void> => {
      if (reading) return
      reading = true
      try {
        const result = await window.paa.company({ action: 'status' })
        if (alive) onChange(result)
      } catch {
        /* The local core can reconnect independently. */
      } finally {
        reading = false
      }
    }
    void refresh()
    const timer = setInterval(() => void refresh(), 3000)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [visible, onChange])
  const [confirmation, setConfirmation] = useState<'logout' | 'clear' | null>(null)
  const [requestError, setRequestError] = useState('')
  const [pending, setPending] = useState(false)
  const [lastAction, setLastAction] = useState<CompanyRequest['action']>('login')
  const loginDialog = useRef<HTMLDialogElement>(null)
  const feedbackAttempt = useRef(false)
  const disabled = pending || status.busy || status.session === 'authorizing'
  const configured = !!status.serverUrl
  const admin = status.identity?.member.role === 'admin'
  useEffect(() => {
    if (!visible) loginDialog.current?.close()
    else if (feedbackAttempt.current && !pending && status.session !== 'authorizing') {
      if (requestError || status.error) loginDialog.current?.showModal()
      feedbackAttempt.current = false
    }
  }, [visible, pending, requestError, status.error, status.session])
  async function run(input: CompanyRequest): Promise<void> {
    feedbackAttempt.current = true
    setLastAction(input.action)
    setPending(true)
    setRequestError('')
    setConfirmation(null)
    try {
      onChange(await window.paa.company(input))
    } catch {
      setRequestError('操作未完成，请重试。')
    } finally {
      setPending(false)
    }
  }
  const voiceprintState =
    status.engine?.error ||
    (status.engine?.state === 'processing'
      ? '正在识别发言者'
      : status.engine?.enabled
        ? '离线可用'
        : '等待本地识别就绪')
  return (
    <section className="company-settings" aria-label="公司连接">
      <section className="settings-card company-account">
        <div className="company-card-heading">
          <span className="company-card-icon">
            <Building2 size={20} />
          </span>
          <div className="company-card-copy">
            <div className="company-card-title">
              <h2>{status.identity?.company.name ?? '公司账号'}</h2>
              {status.session === 'expired' && (
                <span className="company-session-badge">登录已过期</span>
              )}
            </div>
            <p>
              {status.identity
                ? `${status.identity.member.name} · ${admin ? '管理员' : '用户'}`
                : '通过浏览器登录，连接你的公司。'}
            </p>
          </div>
          <div className="company-card-actions">
            {(!status.identity || status.session === 'expired') && (
              <button
                className="primary-button"
                onClick={() => void run({ action: 'login' })}
                disabled={disabled}
              >
                <ExternalLink size={16} />
                {status.session === 'authorizing'
                  ? '等待授权…'
                  : pending && lastAction === 'login'
                    ? '连接中…'
                    : status.session === 'expired'
                      ? '重新登录'
                      : '登录公司账号'}
              </button>
            )}
            {status.identity && (
              <button
                className="secondary-button"
                onClick={() => setConfirmation('logout')}
                disabled={pending}
              >
                <LogOut size={15} />
                退出账号
              </button>
            )}
          </div>
        </div>
        {status.session === 'authorizing' && (
          <div className="company-authorizing" role="status">
            <span>请在浏览器中确认登录。</span>
            <button className="text-button" onClick={() => void run({ action: 'cancel' })}>
              取消登录
            </button>
          </div>
        )}
      </section>
      <section className="settings-card company-voiceprints">
        <div className="company-card-heading">
          <span className="company-card-icon">
            <Fingerprint size={20} />
          </span>
          <div className="company-card-copy">
            <h2>员工声纹</h2>
            <p role="status">
              {!!status.profileCount && (
                <span
                  className={`company-status-dot ${status.engine?.enabled ? 'available' : ''}`}
                />
              )}
              {status.profileCount
                ? `${status.profileCount} 位成员 · ${voiceprintState}`
                : admin
                  ? '尚未同步员工声纹'
                  : '登录公司管理员账号后可同步'}
            </p>
          </div>
          <div className="company-card-actions">
            <button
              className="secondary-button"
              disabled={disabled || !configured || !admin || status.session === 'expired'}
              onClick={() => void run({ action: 'sync' })}
            >
              <RefreshCw size={16} />
              {status.busy && lastAction === 'sync' ? '同步中…' : '同步声纹'}
            </button>
          </div>
        </div>
        {status.syncedAt && (
          <div className="company-cache-footer">
            <small>上次同步：{new Date(status.syncedAt).toLocaleString()}</small>
            <button
              className="text-button"
              disabled={pending}
              onClick={() => setConfirmation('clear')}
            >
              <Trash2 size={15} />
              清除声纹缓存
            </button>
          </div>
        )}
      </section>
      <dialog className="library-dialog" ref={loginDialog} aria-labelledby="company-login-error">
        <form method="dialog">
          <h2 id="company-login-error">
            {lastAction === 'login'
              ? '登录未完成'
              : lastAction === 'sync'
                ? '同步未完成'
                : '操作未完成'}
          </h2>
          <p>{requestError || status.error}</p>
          <div className="button-row">
            <button className="secondary-button">关闭</button>
            {configured && lastAction === 'login' && (
              <button
                type="button"
                className="primary-button"
                disabled={disabled}
                onClick={() => {
                  loginDialog.current?.close()
                  void run({ action: 'login' })
                }}
              >
                重试登录
              </button>
            )}
          </div>
        </form>
      </dialog>
      {confirmation && (
        <div
          className="company-confirmation"
          role="alertdialog"
          aria-label={confirmation === 'logout' ? '退出公司账号' : '清除声纹缓存'}
        >
          <p>
            {confirmation === 'logout'
              ? '退出后将移除此账号在本机的登录信息和员工声纹。'
              : '清除后将停止使用公司声纹，需要联网重新同步。'}
            已有会议和文字记录会保留。
          </p>
          <div>
            <button className="secondary-button" onClick={() => setConfirmation(null)}>
              取消
            </button>
            <button
              className="primary-button"
              disabled={pending}
              onClick={() => void run({ action: confirmation })}
            >
              确认{confirmation === 'logout' ? '退出' : '清除'}
            </button>
          </div>
        </div>
      )}
    </section>
  )
}
