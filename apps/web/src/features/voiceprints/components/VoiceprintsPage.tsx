import layoutStyles from '../../../styles/layout.module.css'
import utilitiesStyles from '../../../styles/utilities.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import voiceprintsStyles from '../styles/voiceprints.module.css'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { manageVoiceprint, voiceprintsPath } from '@web/features/voiceprints/api/requests'
import type { Enrollment, VoiceprintList } from '@web/features/voiceprints/api/types'
import { status } from '@web/features/voiceprints/api/types'
import { EnrollmentForm } from '@web/features/voiceprints/components/EnrollmentForm'
import { useResource } from '@web/hooks/useResource'
import { dateLabel } from '@web/utils/date'
import { AudioLines, CheckCircle2, CircleUserRound, RefreshCw, Trash2, Upload } from 'lucide-react'
import { useEffect, useState } from 'react'

export function VoiceprintsPage() {
  const resource = useResource<VoiceprintList>(voiceprintsPath())
  const processing = !!resource.data?.items.some(
    (v) => v.state === 'queued' || v.state === 'processing',
  )
  const { refresh, error: loadError } = resource
  const [selected, setSelected] = useState<Enrollment | null>(null)
  const [error, setError] = useState<Error | string>('')
  const [busy, setBusy] = useState('')
  const [search, setSearch] = useState('')
  useEffect(() => {
    if (!processing || loadError) return
    const timer = window.setInterval(() => {
      if (!document.hidden) refresh()
    }, 3000)
    return () => window.clearInterval(timer)
  }, [processing, loadError, refresh])
  const items =
    resource.data?.items.filter((v) =>
      v.name.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()),
    ) ?? []
  const act = async (item: Enrollment, action: 'retry' | 'delete') => {
    if (
      action === 'delete' &&
      !window.confirm(`删除 ${item.name} 的声纹及登记录音？已下载到离线桌面的副本不会被移除。`)
    )
      return
    setBusy(item.memberId)
    setError('')
    try {
      await manageVoiceprint(item, action, {}, action === 'retry' ? 'POST' : 'DELETE')
      resource.refresh()
    } catch (e) {
      setError(e as Error)
    } finally {
      setBusy('')
    }
  }
  return (
    <div className={layoutStyles['settings-page']}>
      <header className={voiceprintsStyles['voiceprint-heading']}>
        <div>
          <h2>公司声纹</h2>
          <p className={utilitiesStyles['muted']}>登记成员的声音，让桌面会议助手识别发言者。</p>
        </div>
        <button onClick={resource.refresh} aria-label="刷新声纹">
          <RefreshCw size={16} />
          刷新
        </button>
      </header>
      <ErrorNotice retry={resource.refresh}>{resource.error || error}</ErrorNotice>
      <section className={`${layoutStyles['panel']} ${voiceprintsStyles['voiceprint-library']}`}>
        <div className={voiceprintsStyles['voiceprint-toolbar']}>
          <span>
            <AudioLines size={18} /> {resource.data?.items.filter((v) => v.ready).length ?? 0}{' '}
            位成员已登记
          </span>
          <input
            type="search"
            aria-label="搜索声纹成员"
            placeholder="搜索成员"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div>
          {items.map((item) => {
            const processing = ['queued', 'processing'].includes(item.state)
            return (
              <article key={item.memberId} className={voiceprintsStyles['voiceprint-member']}>
                <span className={voiceprintsStyles['voiceprint-avatar']}>
                  <CircleUserRound size={24} />
                </span>
                <div className={voiceprintsStyles['voiceprint-member-info']}>
                  <strong>
                    {item.name}
                    {item.role === 'admin' && <small>管理员</small>}
                  </strong>
                  <span className={voiceprintsStyles['voiceprint-status']} data-ready={item.ready}>
                    {item.ready && <CheckCircle2 size={14} />}
                    {item.active ? status[item.state] : '成员已停用'}
                    {item.ready && item.state !== 'ready' ? ' · 原声纹仍可用' : ''}
                  </span>
                  {item.updatedAt && (
                    <small>
                      {dateLabel(item.updatedAt)}
                      {item.speechSeconds > 0 ? ` · 有效声音 ${item.speechSeconds} 秒` : ''}
                    </small>
                  )}
                  {item.error && (
                    <p className={voiceprintsStyles['voiceprint-error']}>{item.error}</p>
                  )}
                </div>
                <div className={voiceprintsStyles['voiceprint-actions']}>
                  {item.state === 'failed' && (
                    <button
                      disabled={busy === item.memberId}
                      onClick={() => void act(item, 'retry')}
                    >
                      <RefreshCw size={15} />
                      重试
                    </button>
                  )}
                  <button
                    disabled={!item.active || processing || busy === item.memberId}
                    onClick={() => setSelected(item)}
                  >
                    <Upload size={15} />
                    {item.ready ? '替换录音' : '上传录音'}
                  </button>
                  {item.state !== 'empty' && (
                    <button
                      className={controlsStyles['icon-button']}
                      aria-label={`删除 ${item.name} 的声纹`}
                      disabled={busy === item.memberId}
                      onClick={() => void act(item, 'delete')}
                    >
                      <Trash2 size={16} />
                    </button>
                  )}
                </div>
              </article>
            )
          })}
          {!items.length && (
            <p className={`${utilitiesStyles['muted']} ${voiceprintsStyles['voiceprint-empty']}`}>
              {resource.data ? '没有匹配的成员' : '正在读取成员…'}
            </p>
          )}
        </div>
      </section>
      {selected && (
        <EnrollmentForm
          item={selected}
          onClose={() => setSelected(null)}
          onSaved={() => {
            setSelected(null)
            resource.refresh()
          }}
        />
      )}
    </div>
  )
}
