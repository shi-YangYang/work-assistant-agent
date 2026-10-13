import { DetailBackLink } from '@web/components/navigation/DetailBackLink'
import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router'
import type { Announcement } from '@paa/api-contracts'
import { ApiError, isCancelled } from '@web/api/client'
import { PageHeader } from '@web/components/layout/page-header/PageHeader'
import { Markdown } from '@web/components/content/Markdown'
import { ErrorNoticeView as ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { useResource } from '@web/hooks/useResource'
import { dateLabel } from '@web/utils/date'
import { announcementDetailPath, markAnnouncementRead } from '../api/requests'
import { DeleteAnnouncementDialog, type DeletingAnnouncement } from './DeleteAnnouncementDialog'
import controls from '@web/styles/controls.module.css'
import styles from './Announcements.module.css'

export function announcementReturn(state: unknown, management: boolean) {
  const fallback = management ? '/announcement-management' : '/notifications?tab=announcements'
  const target = (state as { returnTo?: string } | null)?.returnTo
  const base = management ? '/announcement-management' : '/notifications'
  return target && (target === base || target.startsWith(base + '?')) ? target : fallback
}

export function AnnouncementDetail({ management = false }: { management?: boolean }) {
  const { id = '' } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const back = announcementReturn(location.state, management)
  const resource = useResource<Announcement>(announcementDetailPath(id, management))
  const refresh = resource.refresh
  const item = resource.data
  const [error, setError] = useState<Error | string>('')
  const [deleting, setDeleting] = useState<DeletingAnnouncement | null>(null)
  const [readRetry, retryRead] = useState(0)
  const marked = useRef('')
  useEffect(() => {
    const onFocus = () => {
      if (!document.hidden) refresh()
    }
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [refresh])
  useEffect(() => {
    if (management || !item || !item.unread) return
    const key = `${item.id}:${item.revision}:${readRetry}`
    let active = true
    const read = () => {
      if (document.hidden || marked.current === key) return
      marked.current = key
      void markAnnouncementRead(item.id, item.revision)
        .then(() => {
          window.dispatchEvent(new Event('paa-notifications-changed'))
          if (active) setError('')
        })
        .catch((failure) => {
          if (!active || isCancelled(failure)) return
          setError(failure as Error)
          if (failure instanceof ApiError && [404, 409].includes(failure.status)) refresh()
        })
    }
    // Wait for the committed detail, including StrictMode's initial cleanup.
    const timer = setTimeout(read, 0)
    document.addEventListener('visibilitychange', read)
    return () => {
      active = false
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', read)
    }
  }, [item, management, readRetry, refresh])
  return (
    <div className={styles.page} data-scroll-container>
      <DetailBackLink
        destination={{ path: back, state: null }}
        label={management ? '返回公告管理' : '返回通知'}
      />
      <ErrorNotice
        retry={() => {
          setError('')
          retryRead((value) => value + 1)
          resource.refresh()
        }}
      >
        {resource.error || error}
      </ErrorNotice>
      {!item && !resource.error && <p>正在读取公告…</p>}
      {item && (
        <>
          <PageHeader
            context="detail"
            title={item.title}
            actions={
              management ? (
                <div className={styles.actions}>
                  {item.state === 'published' && (
                    <Link
                      to={`/announcement-management/${item.id}/edit`}
                      state={{ returnTo: back }}
                    >
                      编辑
                    </Link>
                  )}
                  <button
                    type="button"
                    className={controls.danger}
                    onClick={() => setDeleting(item)}
                  >
                    删除
                  </button>
                </div>
              ) : undefined
            }
          />
          <div className={styles.meta}>
            <span>发布人：{item.authorName}</span>
            <time>{dateLabel(item.publishedAt)}</time>
            {item.revision > 1 && (
              <span>
                已更新 {dateLabel(item.updatedAt)} · {item.editorName}
              </span>
            )}
            {item.state === 'withdrawn' && <span>不可用</span>}
          </div>
          <article className={styles.body}>
            <Markdown text={item.markdown} />
          </article>
        </>
      )}
      {management && deleting && (
        <DeleteAnnouncementDialog
          item={deleting}
          onClose={() => setDeleting(null)}
          onDeleted={() => navigate(back, { replace: true })}
          onConflict={refresh}
        />
      )}
    </div>
  )
}
