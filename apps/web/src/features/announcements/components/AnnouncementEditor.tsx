import { DetailBackLink } from '@web/components/navigation/DetailBackLink'
import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router'
import type { Announcement, AnnouncementContent } from '@paa/api-contracts'
import { ApiError, isCancelled } from '@web/api/client'
import { BusyButton } from '@web/components/actions/BusyButton'
import { ErrorNoticeView as ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { MarkdownEditor } from '@web/components/forms/markdown-editor/MarkdownEditor'
import { PageHeader } from '@web/components/layout/page-header/PageHeader'
import { useResource } from '@web/hooks/useResource'
import { useWorkspace } from '@web/lib/workspace'
import {
  announcementDetailPath,
  editAnnouncement,
  publishAnnouncement,
  readAnnouncement,
} from '../api/requests'
import { announcementReturn } from './AnnouncementDetail'
import controls from '@web/styles/controls.module.css'
import styles from './Announcements.module.css'

type Draft = AnnouncementContent & {
  revision?: number
  pending?: { key: string; body: AnnouncementContent }
}
export function AnnouncementEditor() {
  const { id } = useParams()
  const { drafts, setDraft, notify } = useWorkspace()
  const location = useLocation()
  const navigate = useNavigate()
  const key = `announcement:${id ?? 'new'}`
  const back = announcementReturn(location.state, true)
  const source = useResource<Announcement>(id ? announcementDetailPath(id, true) : null)
  const draft = drafts[key] as Draft | undefined
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | string>('')
  const inFlight = useRef(false)
  useEffect(() => {
    if (draft) return
    if (!id) setDraft(key, { title: '', markdown: '' })
    else if (source.data)
      setDraft(key, {
        title: source.data.title,
        markdown: source.data.markdown,
        revision: source.data.revision,
      })
  }, [draft, id, source.data, key, setDraft])
  const tooLong =
    !!draft && (Array.from(draft.title).length > 100 || Array.from(draft.markdown).length > 20000)
  const unavailable =
    source.data?.state === 'withdrawn' ||
    (source.error instanceof ApiError && source.error.status === 404)
  const conflict = error instanceof ApiError && error.status === 409
  const save = async () => {
    if (
      !draft ||
      inFlight.current ||
      tooLong ||
      unavailable ||
      !draft.title.trim() ||
      !draft.markdown.trim()
    )
      return
    const pending = draft.pending ?? {
      key: crypto.randomUUID(),
      body: { title: draft.title.trim(), markdown: draft.markdown.trim() },
    }
    setDraft(key, { ...draft, pending })
    inFlight.current = true
    setBusy(true)
    setError('')
    try {
      const result = id
        ? await editAnnouncement(id, pending.body, draft.revision!)
        : await publishAnnouncement(pending.body, pending.key)
      setDraft(key, undefined)
      window.dispatchEvent(new Event('paa-notifications-changed'))
      notify(id ? '公告已保存' : '公告已发布')
      navigate(`/announcement-management/${result.id}`, {
        replace: true,
        state: { returnTo: back },
      })
    } catch (failure) {
      if (!isCancelled(failure)) setError(failure as Error)
      if (failure instanceof ApiError && failure.status >= 400 && failure.status < 500)
        setDraft(key, { ...draft, pending: undefined })
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }
  return (
    <div className={styles.page} data-scroll-container>
      <DetailBackLink destination={{ path: back, state: null }} label="返回公告管理" />
      <PageHeader context="detail" title={id ? '编辑公告' : '发布公告'} />
      <ErrorNotice retry={source.refresh}>{source.error}</ErrorNotice>
      {unavailable && <p>公告已删除或不可用，不能继续修改。未保存的草稿仍保留。</p>}
      {draft ? (
        <form
          className={styles.form}
          onSubmit={(event) => {
            event.preventDefault()
            void save()
          }}
        >
          <label>
            标题
            <input
              aria-label="公告标题"
              required
              value={draft.title}
              disabled={busy || !!draft.pending || unavailable}
              onChange={(event) => setDraft(key, { ...draft, title: event.target.value })}
            />
          </label>
          <MarkdownEditor
            label="公告正文"
            value={draft.markdown}
            onChange={(markdown) => setDraft(key, { ...draft, markdown })}
            disabled={busy || !!draft.pending || unavailable}
            invalid={tooLong}
            placeholder="写下要告诉大家的事情…"
            metadata={<span>{Array.from(draft.markdown).length} / 20,000 字符</span>}
          />
          <small>
            标题最多 100 字符，正文最多 20,000 字符。支持
            Markdown，不支持图片和附件；离页后草稿会保留。
          </small>
          {tooLong && <p role="alert">标题或正文超出长度，请缩短后再提交。</p>}
          {draft.pending && <p>提交结果待确认，请原样重试。</p>}
          <ErrorNotice>{error}</ErrorNotice>
          {conflict && (
            <button
              type="button"
              onClick={async () => {
                if (!window.confirm('读取最新公告并替换当前草稿？')) return
                try {
                  const latest = await readAnnouncement(id!)
                  setDraft(key, {
                    title: latest.title,
                    markdown: latest.markdown,
                    revision: latest.revision,
                  })
                  setError('')
                  source.refresh()
                } catch (failure) {
                  if (!isCancelled(failure)) setError(failure as Error)
                }
              }}
            >
              读取最新版本
            </button>
          )}
          <div className={styles.actions}>
            <BusyButton
              className={controls.primary}
              busy={busy}
              disabled={
                tooLong || unavailable || conflict || !draft.title.trim() || !draft.markdown.trim()
              }
            >
              {draft.pending ? '原样重试' : id ? '保存修改' : '发布'}
            </BusyButton>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                if (window.confirm('放弃当前草稿？')) {
                  setDraft(key, undefined)
                  navigate(back)
                }
              }}
            >
              放弃草稿
            </button>
          </div>
        </form>
      ) : (
        !source.error && <p>正在读取公告…</p>
      )}
    </div>
  )
}
