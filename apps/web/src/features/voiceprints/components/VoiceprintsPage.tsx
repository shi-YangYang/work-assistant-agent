import { SearchInput } from '@web/components/forms/SearchInput'
import searchStyles from '@web/styles/patterns/SearchInput.module.css'
import { ListToolbar } from '@web/components/layout/list-toolbar/ListToolbar'
import { PageHeader } from '@web/components/layout/page-header/PageHeader'
import layoutStyles from '../../../styles/layout.module.css'
import utilitiesStyles from '../../../styles/utilities.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import voiceprintsStyles from '../styles/voiceprints.module.css'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { ActionNotice } from '@web/components/feedback/ActionNotice'
import { ConfirmDialog } from '@web/components/overlays/ConfirmDialog'
import { manageVoiceprint, voiceprintsPath } from '@web/features/voiceprints/api/requests'
import type { Enrollment, VoiceprintList } from '@web/features/voiceprints/api/types'
import { status } from '@web/features/voiceprints/api/types'
import { VoiceprintCleanup } from '@web/features/voiceprints/components/VoiceprintCleanup'
import { EnrollmentForm } from '@web/features/voiceprints/components/EnrollmentForm'
import { useResource } from '@web/hooks/useResource'
import { dateLabel } from '@web/utils/date'
import {
  Search,
  AudioLines,
  CheckCircle2,
  CircleUserRound,
  RefreshCw,
  Trash2,
  Upload,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

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
  const [removing, setRemoving] = useState<Enrollment | null>(null)
  const [deleteError, setDeleteError] = useState<Error | string>('')
  const pending = useRef(false)
  const deletedMember = useRef('')
  const uploadButtons = useRef(new Map<string, HTMLButtonElement>())
  const library = useRef<HTMLElement>(null)
  useEffect(() => {
    if (!removing && deletedMember.current) {
      const upload = uploadButtons.current.get(deletedMember.current)
      if (upload && !upload.disabled) upload.focus()
      else library.current?.focus()
      deletedMember.current = ''
    }
  }, [removing])
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
    if (pending.current) return
    pending.current = true
    setBusy(item.memberId)
    setError('')
    setDeleteError('')
    try {
      await manageVoiceprint(item, action, {}, action === 'retry' ? 'POST' : 'DELETE')
      if (action === 'delete') {
        deletedMember.current = item.memberId
        setRemoving(null)
      }
      resource.refresh()
    } catch (e) {
      if (action === 'delete') setDeleteError(e as Error)
      else setError(e as Error)
    } finally {
      pending.current = false
      setBusy('')
    }
  }
  return (
    <div className={layoutStyles['settings-page']}>
      <PageHeader
        title="用户声纹"
        description="登记成员的声音，让 Noria 桌面端识别发言者。"
        actions={
          <button
            className={controlsStyles['icon-button']}
            onClick={resource.refresh}
            aria-label="刷新声纹"
          >
            <RefreshCw size={16} />
          </button>
        }
      />
      <ErrorNotice retry={resource.refresh}>{resource.error}</ErrorNotice>
      <ActionNotice>{error}</ActionNotice>
      <section ref={library} tabIndex={-1} className={voiceprintsStyles['voiceprint-library']}>
        <ListToolbar
          actions={
            <span className={voiceprintsStyles['voiceprint-count']}>
              <AudioLines size={18} /> {resource.data?.items.filter((v) => v.ready).length ?? 0}{' '}
              位成员已登记
            </span>
          }
        >
          <div className={searchStyles['work-search']}>
            <Search size={17} aria-hidden="true" />
            <SearchInput
              aria-label="搜索声纹成员"
              placeholder="搜索姓名或账号"
              value={search}
              onSearch={setSearch}
            />
          </div>
        </ListToolbar>
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
                    <button disabled={!!busy} onClick={() => void act(item, 'retry')}>
                      <RefreshCw size={15} />
                      重试
                    </button>
                  )}
                  <button
                    ref={(button) => {
                      if (button) uploadButtons.current.set(item.memberId, button)
                      else uploadButtons.current.delete(item.memberId)
                    }}
                    disabled={!item.active || processing || !!busy}
                    onClick={() => setSelected(item)}
                  >
                    <Upload size={15} />
                    {item.ready ? '替换录音' : '上传录音'}
                  </button>
                  {item.state !== 'empty' && (
                    <button
                      className={controlsStyles['icon-button']}
                      aria-label={`删除 ${item.name} 的声纹`}
                      disabled={!!busy}
                      onClick={(event) => {
                        event.currentTarget.focus()
                        setDeleteError('')
                        setRemoving(item)
                      }}
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
      <VoiceprintCleanup refresh={resource.refresh} />
      {removing && (
        <ConfirmDialog
          title="删除声纹"
          confirmLabel="确认删除"
          danger
          busy={!!busy}
          error={deleteError}
          onClose={() => {
            if (!pending.current) setRemoving(null)
          }}
          onConfirm={() => void act(removing, 'delete')}
        >
          <p>删除 {removing.name} 的声纹及登记录音？已下载到离线桌面的副本不会被移除。</p>
        </ConfirmDialog>
      )}
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
