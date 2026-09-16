import { useRef, useState } from 'react'
import { useLocation } from 'react-router'
import type { SupportDiagnostics, SupportFeedback, SupportFeedbackCreate } from '@paa/api-contracts'
import { api, ApiError, dateLabel, write, useRetryWait } from './api'
import { captureDiagnostics, copyText, diagnosticText } from './diagnostics'
import { useCursorPage } from './list-state'
import { Pagination } from './ListControls'
import { useWorkspace } from './workspace'
import { AutoTextarea, BusyButton, ErrorNotice, Modal } from './ui'

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
  const search = new URLSearchParams(location.search)
  const scope = admin && search.get('scope') !== 'mine' ? 'all' : 'mine'
  const filterState = ['pending', 'resolved'].includes(search.get('state') ?? '')
    ? search.get('state')!
    : ''
  const list = useCursorPage<SupportFeedback>(
    `/support-feedback?scope=${scope}${filterState ? `&state=${filterState}` : ''}`,
  )
  const text = `${draft.description || '（请填写问题描述）'}\n\n${diagnosticText(draft.diagnostics)}`
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
      await write<SupportFeedback>('/support-feedback', pending.body, 'POST', pending.key)
      setDraft('support', undefined)
      list.refresh()
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
    <div className="settings-page support-page">
      <h2>问题反馈</h2>
      <p className="muted">描述遇到的问题，由本公司管理员处理。</p>
      <form
        className="panel"
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
            onChange={(event) => setDraft('support', { ...draft, description: event.target.value })}
            placeholder="你做了什么，遇到了什么问题？"
          />
        </label>
        <details>
          <summary>查看本次诊断摘要</summary>
          <p className="muted">
            仅包含以下环境信息，不自动采集聊天、文件或完整网址。请勿在描述中填写密码或密钥。
          </p>
          <pre className="diagnostic-summary">{diagnosticText(draft.diagnostics)}</pre>
        </details>
        {draft.pending && (
          <p className="muted">提交结果待确认，请原样重试；本次反馈不会重复创建。</p>
        )}
        <ErrorNotice>{error}</ErrorNotice>
        <div className="form-actions">
          <button
            type="button"
            onClick={() =>
              void copyText(text).then(
                () => notify('已复制反馈信息'),
                (failure: Error) => setError(failure),
              )
            }
          >
            复制反馈信息
          </button>
          <BusyButton
            className="primary"
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
      <div className="page-heading">
        <h3>{scope === 'all' ? '公司反馈' : '我的反馈'}</h3>
        <div className="support-filters">
          {admin && (
            <label>
              查看范围
              <select
                value={scope}
                onChange={(event) => list.filter({ scope: event.target.value })}
              >
                <option value="mine">我的反馈</option>
                <option value="all">公司反馈</option>
              </select>
            </label>
          )}
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
      </div>
      <ErrorNotice retry={list.refresh}>{list.error}</ErrorNotice>
      {!list.data && !list.error && <p className="muted">正在读取反馈…</p>}
      {list.data && !list.data.items.length && <p className="muted">暂无反馈</p>}
      <div className="support-list">
        {list.data?.items.map((item) => (
          <button className="panel support-item" key={item.id} onClick={() => open(item)}>
            <span className="row-between">
              <strong>{item.state === 'pending' ? '待处理' : '已处理'}</strong>
              <time>{dateLabel(item.createdAt)}</time>
            </span>
            {admin && <small>{item.ownerName}</small>}
            <span className="preserve">{item.description}</span>
            {item.handlingNote && (
              <span className="muted preserve">处理说明：{item.handlingNote}</span>
            )}
          </button>
        ))}
      </div>
      <Pagination
        page={list.page}
        hasNext={!!list.data?.nextCursor}
        previous={list.previous}
        next={list.next}
      />
      {selected && (
        <Modal title="反馈详情" onClose={() => !busy && setSelected(null)}>
          <p className="preserve">{selected.description}</p>
          <pre className="diagnostic-summary">{diagnosticText(selected.diagnostics)}</pre>
          {admin ? (
            <form
              onSubmit={async (event) => {
                event.preventDefault()
                if (inFlight.current) return
                inFlight.current = true
                setBusy(true)
                setError('')
                try {
                  const saved = await write<SupportFeedback>(
                    `/support-feedback/${selected.id}`,
                    { state, handlingNote: note, expectedRevision: selected.revision },
                    'PATCH',
                  )
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
                      open(await api<SupportFeedback>(`/support-feedback/${selected.id}`))
                    } catch (failure) {
                      setError(failure as Error)
                    }
                  }}
                >
                  读取最新处理结果
                </button>
              )}
              <div className="form-actions">
                <BusyButton busy={busy} className="primary">
                  保存处理结果
                </BusyButton>
              </div>
            </form>
          ) : (
            <p className="preserve">
              {selected.state === 'pending' ? '待处理' : '已处理'} ·{' '}
              {selected.handlingNote || '暂无处理说明'}
            </p>
          )}
        </Modal>
      )}
    </div>
  )
}
