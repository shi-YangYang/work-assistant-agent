import { useEffect, useState } from 'react'
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
  const [server, setServer] = useState<string | null>(null)
  const [confirmation, setConfirmation] = useState<'logout' | 'clear' | null>(null)
  const [requestError, setRequestError] = useState('')
  const [pending, setPending] = useState(false)
  const disabled = pending || status.busy || status.session === 'authorizing'
  const admin = status.identity?.member.role === 'admin'
  async function run(input: CompanyRequest): Promise<void> {
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
  return (
    <section className="company-settings" aria-label="公司连接">
      {(status.error || requestError) && (
        <div className="error-banner" role="alert">
          {requestError || status.error}
        </div>
      )}
      <section className="settings-card company-account">
        <div className="company-card-heading">
          <Building2 size={22} />
          <div>
            <h2>{status.identity?.company.name ?? '连接你的公司'}</h2>
            <p>
              {status.identity
                ? `${status.identity.member.name} · ${admin ? '管理员' : '用户'}`
                : '未登录时，也可以继续使用本地会议。'}
            </p>
          </div>
          <span className="company-session-badge">
            {status.session === 'authorizing'
              ? '等待授权'
              : status.session === 'expired'
                ? '需要重新登录'
                : status.identity
                  ? '已登录'
                  : '游客'}
          </span>
        </div>
        <form
          className="company-login-form"
          onSubmit={(event) => {
            event.preventDefault()
            void run({
              action: 'login',
              serverUrl: status.identity ? status.serverUrl : (server ?? status.serverUrl),
            })
          }}
        >
          <label htmlFor="company-address">公司 Web 地址</label>
          <div className="company-address-row">
            <input
              id="company-address"
              type="url"
              placeholder="https://assistant.example.com"
              value={status.identity ? status.serverUrl : (server ?? status.serverUrl)}
              onChange={(event) => setServer(event.target.value)}
              disabled={disabled || !!status.identity}
              autoComplete="url"
              required
            />
            <button className="primary-button" type="submit" disabled={disabled}>
              <ExternalLink size={16} />
              {status.session === 'expired'
                ? '重新登录'
                : status.identity
                  ? '浏览器登录'
                  : '连接并登录'}
            </button>
          </div>
        </form>
        {status.session === 'authorizing' && (
          <div className="company-authorizing" role="status">
            <span>请在浏览器中登录并确认连接，完成后会自动返回登录状态。</span>
            <button className="text-button" onClick={() => void run({ action: 'cancel' })}>
              取消登录
            </button>
          </div>
        )}
        {status.identity && (
          <div className="company-account-actions">
            <button
              className="text-button"
              onClick={() => setConfirmation('logout')}
              disabled={pending}
            >
              <LogOut size={15} />
              退出公司账号
            </button>
          </div>
        )}
      </section>
      <section className="settings-card company-voiceprints">
        <div className="company-card-heading">
          <Fingerprint size={22} />
          <div>
            <h2>员工声纹</h2>
            <p>
              {status.profileCount
                ? `${status.profileCount} 位成员 · 已保存在本机`
                : '同步后即可在本机匹配员工姓名'}
            </p>
          </div>
          <button
            className="secondary-button"
            disabled={disabled || !admin || status.session === 'expired'}
            onClick={() => void run({ action: 'sync' })}
          >
            <RefreshCw size={16} />
            {status.busy ? '同步中…' : '同步声纹'}
          </button>
        </div>
        <div className="company-voiceprint-status" role="status">
          <span
            className={`company-status-dot ${status.profileCount && status.engine?.enabled ? 'available' : ''}`}
          />
          <span>
            {status.profileCount
              ? status.engine?.error ||
                (status.engine?.state === 'processing'
                  ? '正在本地识别发言者'
                  : status.engine?.enabled
                    ? '本地识别已就绪，离线也可使用'
                    : '声纹已保存，等待本地识别就绪')
              : admin
                ? '尚未同步声纹，请先在公司 Web 登记成员录音'
                : status.identity
                  ? '公司声纹由管理员同步'
                  : '以公司管理员身份登录后同步'}
          </span>
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
