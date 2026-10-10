import { PageHeader } from '@web/components/layout/page-header/PageHeader'
import layoutStyles from '../../../styles/layout.module.css'
import utilitiesStyles from '../../../styles/utilities.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import styles from './SupportPage.module.css'
import type { SupportDiagnostics, SupportFeedback, SupportFeedbackCreate } from '@paa/api-contracts'
import { ApiError } from '@web/api/client'
import { AutoTextarea } from '@web/components/forms/AutoTextarea'
import { BusyButton } from '@web/components/actions/BusyButton'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { Modal } from '@web/components/overlays/Modal'
import { Pagination } from '@web/components/actions/Pagination'
import {
  feedbackListPath,
  handleFeedback,
  readFeedback,
  submitFeedback,
} from '@web/features/feedback/api/requests'
import { useCursorPage } from '@web/hooks/useCursorPage'
import { useRetryWait } from '@web/hooks/useRetryWait'
import { captureDiagnostics, diagnosticText } from '@web/lib/diagnostics'
import { useWorkspace } from '@web/lib/workspace'
import { dateLabel } from '@web/utils/date'
import { Inbox } from 'lucide-react'
import { useRef, useState } from 'react'
import { useLocation, useSearchParams } from 'react-router'

const tabs = [
  { id: 'submit', label: '提交反馈' },
  { id: 'records', label: '反馈记录' },
] as const

type FeedbackDraft = {
  description: string
  diagnostics: SupportDiagnostics
  pending?: { key: string; body: SupportFeedbackCreate }
}

export function SupportPage() {
  const { identity, drafts, setDraft, notify } = useWorkspace()
  const location = useLocation()
  const [initial] = useState<SupportDiagnostics>(
    () =>
      (location.state as { diagnostics?: SupportDiagnostics } | null)?.diagnostics ??
      captureDiagnostics(),
  )
  const draft = (drafts.support as FeedbackDraft | undefined) ?? {
    description: '',
    diagnostics: initial,
  }
  const [error, setError] = useState<Error | string>('')
  const [busy, setBusy] = useState(false)
  const retryWait = useRetryWait(error)
  const inFlight = useRef(false)
  const [selected, setSelected] = useState<SupportFeedback | null>(null)
  const [note, setNote] = useState('')
  const [state, setState] = useState<'pending' | 'resolved'>('pending')
  const admin = identity.member.role === 'admin'
  const [search, setSearch] = useSearchParams()
  const tab =
    search.get('tab') === 'records' ||
    (!search.has('tab') && ['scope', 'state', 'after'].some((key) => search.has(key)))
      ? 'records'
      : 'submit'
  const selectTab = (next: (typeof tabs)[number]['id']) => {
    const params = new URLSearchParams(search)
    params.set('tab', next)
    setSearch(params, { replace: true, state: location.state })
  }
  const scope = admin ? 'all' : 'mine'
  const filterState = ['pending', 'resolved'].includes(search.get('state') ?? '')
    ? search.get('state')!
    : ''
  const list = useCursorPage<SupportFeedback>(
    tab === 'records' ? feedbackListPath(scope, filterState) : null,
  )
  const submit = async () => {
    if (inFlight.current || retryWait || !draft.description.trim()) return
    const pending = draft.pending ?? {
      key: crypto.randomUUID(),
      body: { description: draft.description.trim(), diagnostics: draft.diagnostics },
    }
    inFlight.current = true
    setBusy(true)
    setError('')
    setDraft('support', { ...draft, pending })
    try {
      await submitFeedback(pending.body, pending.key)
      setDraft('support', undefined)
      list.filter({ tab: 'records', state: '', scope: '' })
      notify('反馈已提交，可在列表查看处理结果。')
    } catch (failure) {
      setError(failure instanceof Error ? failure : '反馈未提交，请重试。')
      if (failure instanceof ApiError && [400, 403, 413, 422, 429].includes(failure.status))
        setDraft('support', { ...draft, pending: undefined })
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }
  const open = (item: SupportFeedback) => {
    setSelected(item)
    setNote(item.handlingNote ?? '')
    setState(item.state)
    setError('')
  }
  return (
    <div
      className={`${layoutStyles['settings-page']} ${layoutStyles['settings-form-page']} ${styles['support-page']}`}
    >
      <PageHeader title="问题反馈" description="描述遇到的问题，由本公司管理员处理。" />
      <div className={layoutStyles['tabs']} role="tablist" aria-label="问题反馈">
        {tabs.map((item, index) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            id={`support-tab-${item.id}`}
            aria-controls={`support-panel-${item.id}`}
            aria-selected={tab === item.id}
            data-active={tab === item.id}
            tabIndex={tab === item.id ? 0 : -1}
            disabled={busy}
            onClick={() => selectTab(item.id)}
            onKeyDown={(event) => {
              let next: number
              if (event.key === 'ArrowRight') next = (index + 1) % tabs.length
              else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length
              else if (event.key === 'Home') next = 0
              else if (event.key === 'End') next = tabs.length - 1
              else return
              event.preventDefault()
              selectTab(tabs[next].id)
              const buttons =
                event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>(
                  '[role="tab"]',
                )
              buttons?.[next]?.focus()
            }}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div
        role="tabpanel"
        id="support-panel-submit"
        aria-labelledby="support-tab-submit"
        hidden={tab !== 'submit'}
      >
        {tab === 'submit' && (
          <form
            className={`${styles['support-compose']}`}
            aria-label="提交反馈"
            onSubmit={(event) => {
              event.preventDefault()
              void submit()
            }}
          >
            <label>
              问题描述
              <AutoTextarea
                required
                maxLength={4000}
                value={draft.description}
                disabled={busy}
                readOnly={!!draft.pending}
                onChange={(event) =>
                  setDraft('support', { ...draft, description: event.target.value })
                }
                placeholder="你做了什么，遇到了什么问题？"
              />
            </label>
            {draft.pending && (
              <p className={utilitiesStyles['muted']}>
                提交结果待确认，请原样重试；本次反馈不会重复创建。
              </p>
            )}
            <ErrorNotice>{error}</ErrorNotice>
            <div className={`${layoutStyles['form-actions']} ${styles['slot-form-actions']}`}>
              <BusyButton
                className={controlsStyles['primary']}
                busy={busy}
                disabled={!!retryWait || !draft.description.trim()}
              >
                {retryWait
                  ? `${retryWait} 秒后再试`
                  : draft.pending
                    ? '原样重试，确认提交'
                    : '提交反馈'}
              </BusyButton>
            </div>
          </form>
        )}
      </div>
      <div
        role="tabpanel"
        id="support-panel-records"
        aria-labelledby="support-tab-records"
        hidden={tab !== 'records'}
      >
        {tab === 'records' && (
          <div>
            <header className={styles['support-heading']}>
              <div className={styles['support-filters']}>
                <label>
                  处理状态
                  <select
                    value={filterState}
                    onChange={(event) => list.filter({ state: event.target.value })}
                  >
                    <option value="">全部</option>
                    <option value="pending">待处理</option>
                    <option value="resolved">已处理</option>
                  </select>
                </label>
              </div>
            </header>
            <ErrorNotice retry={list.refresh}>{list.error}</ErrorNotice>
            {!list.data && !list.error && <p className={utilitiesStyles['muted']}>正在读取反馈…</p>}
            {list.data && !list.data.items.length && (
              <div className={styles['support-empty']}>
                <Inbox size={30} strokeWidth={1.5} aria-hidden="true" />
                <p>{filterState ? '暂无符合条件的反馈' : '暂无反馈'}</p>
              </div>
            )}
            <div className={styles['support-list']}>
              {list.data?.items.map((item) => (
                <button className={styles['support-item']} key={item.id} onClick={() => open(item)}>
                  <span className={layoutStyles['row-between']}>
                    <span className={styles['support-state']} data-status={item.state}>
                      {item.state === 'pending' ? '待处理' : '已处理'}
                    </span>
                    <time>{dateLabel(item.createdAt)}</time>
                  </span>
                  {admin && <small>{item.ownerName}</small>}
                  <span className={`${utilitiesStyles['preserve']} ${styles['slot-preserve']}`}>
                    {item.description}
                  </span>
                  {item.handlingNote && (
                    <span
                      className={`${utilitiesStyles['muted']} ${utilitiesStyles['preserve']} ${styles['slot-preserve']}`}
                    >
                      处理说明：{item.handlingNote}
                    </span>
                  )}
                </button>
              ))}
            </div>
            {(list.page > 1 || list.data?.nextCursor) && (
              <Pagination
                page={list.page}
                hasNext={!!list.data?.nextCursor}
                previous={list.previous}
                next={list.next}
              />
            )}
          </div>
        )}
      </div>
      {selected && (
        <Modal title="反馈详情" onClose={() => !busy && setSelected(null)}>
          <p className={`${utilitiesStyles['preserve']} ${styles['slot-preserve']}`}>
            {selected.description}
          </p>
          <pre className={styles['diagnostic-summary']}>{diagnosticText(selected.diagnostics)}</pre>
          {admin ? (
            <form
              onSubmit={async (event) => {
                event.preventDefault()
                if (inFlight.current) return
                inFlight.current = true
                setBusy(true)
                setError('')
                try {
                  const saved = await handleFeedback(selected, {
                    state,
                    handlingNote: note,
                    expectedRevision: selected.revision,
                  })
                  setSelected(saved)
                  list.refresh()
                  notify('处理结果已保存')
                } catch (failure) {
                  setError(failure instanceof Error ? failure : '保存未完成')
                } finally {
                  inFlight.current = false
                  setBusy(false)
                }
              }}
            >
              <label>
                状态
                <select
                  value={state}
                  onChange={(event) => setState(event.target.value as typeof state)}
                >
                  <option value="pending">待处理</option>
                  <option value="resolved">已处理</option>
                </select>
              </label>
              <label>
                处理说明
                <AutoTextarea
                  maxLength={2000}
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                />
              </label>
              <ErrorNotice>{error}</ErrorNotice>
              {error instanceof ApiError && error.status === 409 && (
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      open(await readFeedback(selected))
                    } catch (failure) {
                      setError(failure as Error)
                    }
                  }}
                >
                  读取最新处理结果
                </button>
              )}
              <div className={`${layoutStyles['form-actions']} ${styles['slot-form-actions']}`}>
                <BusyButton busy={busy} className={controlsStyles['primary']}>
                  保存处理结果
                </BusyButton>
              </div>
            </form>
          ) : (
            <p className={`${utilitiesStyles['preserve']} ${styles['slot-preserve']}`}>
              {selected.state === 'pending' ? '待处理' : '已处理'} ·{' '}
              {selected.handlingNote || '暂无处理说明'}
            </p>
          )}
        </Modal>
      )}
    </div>
  )
}
