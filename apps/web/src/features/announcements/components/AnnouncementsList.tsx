import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router'
import { ApiError, isCancelled } from '@web/api/client'
import { Empty } from '@web/components/feedback/Empty'
import { ErrorNoticeView as ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { BusyButton } from '@web/components/actions/BusyButton'
import { Pagination } from '@web/components/actions/Pagination'
import { useQueryResource } from '@web/hooks/useQueryResource'
import { dateLabel } from '@web/utils/date'
import { announcementList, markAnnouncementRead } from '../api/requests'
import { useAnnouncementListScroll } from '../hooks/useAnnouncementListScroll'
import { DeleteAnnouncementDialog, type DeletingAnnouncement } from './DeleteAnnouncementDialog'
import controls from '@web/styles/controls.module.css'
import styles from './Announcements.module.css'

export function AnnouncementsList({
  management = false,
  active = true,
}: {
  management?: boolean
  active?: boolean
}) {
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const pageKey = management ? 'page' : 'announcementPage'
  const page = Math.max(1, Math.min(50001, Number(params.get(pageKey)) || 1))
  const resource = announcementList('published', String((page - 1) * 20))
  const list = useQueryResource(resource)
  const listRef = useAnnouncementListScroll(active, !!list.data)
  const [reading, setReading] = useState<string | null>(null)
  const [readError, setReadError] = useState<Error | string>('')
  const marking = useRef(false)
  const [deleting, setDeleting] = useState<DeletingAnnouncement | null>(null)
  useEffect(() => {
    if (active) void resource.refresh()
  }, [active, resource])
  useEffect(() => {
    const update = () => {
      void resource.invalidate()
    }
    window.addEventListener('paa-notifications-changed', update)
    return () => window.removeEventListener('paa-notifications-changed', update)
  }, [resource])
  const move = (next: number) => {
    const updated = new URLSearchParams(params)
    updated.set(pageKey, String(next))
    setParams(updated)
  }
  const markRead = async (id: string, revision: number) => {
    if (marking.current) return
    marking.current = true
    setReading(id)
    setReadError('')
    try {
      await markAnnouncementRead(id, revision)
      window.dispatchEvent(new Event('paa-notifications-changed'))
      await resource.ensure()
    } catch (error) {
      if (!isCancelled(error)) setReadError(error as Error)
      if (error instanceof ApiError && [404, 409].includes(error.status)) void resource.invalidate()
    } finally {
      marking.current = false
      setReading(null)
    }
  }
  return (
    <>
      <ErrorNotice>{readError}</ErrorNotice>
      <ErrorNotice retry={list.refresh}>{list.error}</ErrorNotice>
      {!list.data && !list.error && <p>正在读取公告…</p>}
      {list.data && !list.data.items.length && <Empty title="暂无公告" />}
      <div ref={listRef} className={styles.list}>
        {list.data?.items.map((item) => (
          <div key={item.id} className={styles.row}>
            <Link
              className={styles.item}
              to={`${management ? '/announcement-management' : '/notifications/announcements'}/${item.id}`}
              state={{ returnTo: location.pathname + location.search }}
            >
              <span className={styles.heading}>
                {!management && item.unread && <span className={styles.dot} aria-label="未读" />}
                <strong className={styles.title}>{item.title}</strong>
              </span>
              <p className={styles.summary}>{item.summary}</p>
              <span className={styles.meta}>
                <time>{dateLabel(item.publishedAt)}</time>
                <span>{item.authorName}</span>
                {item.revision > 1 && item.state === 'published' && <span>已更新</span>}
              </span>
            </Link>
            {!management && item.unread && (
              <BusyButton
                type="button"
                className={styles.markRead}
                busy={reading === item.id}
                disabled={reading !== null}
                onClick={() => void markRead(item.id, item.revision)}
              >
                标为已读
              </BusyButton>
            )}
            {management && (
              <button
                type="button"
                className={`${controls.danger} ${styles.rowAction}`}
                onClick={() => setDeleting(item)}
              >
                删除
              </button>
            )}
          </div>
        ))}
      </div>
      {management && deleting && (
        <DeleteAnnouncementDialog
          item={deleting}
          onClose={() => setDeleting(null)}
          onDeleted={() => {
            setDeleting(null)
            if (list.data?.items.length === 1 && page > 1) move(page - 1)
          }}
          onConflict={() => {
            void resource.invalidate()
          }}
        />
      )}
      <Pagination
        page={page}
        hasNext={!!list.data?.nextCursor}
        previous={() => move(Math.max(1, page - 1))}
        next={() => move(page + 1)}
      />
    </>
  )
}
