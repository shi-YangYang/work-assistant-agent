import type { BusinessCitation, BusinessSource } from '@paa/api-contracts'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Markdown } from '@web/components/Markdown'
import { Modal } from '@web/components/Modal'
import { useResource } from '@web/hooks/useResource'
import { dateLabel } from '@web/utils/date'
import { detailState } from '@web/utils/navigation'
import { FileText, Link2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useLocation } from 'react-router'

export function BusinessSources({
  sources,
  endpoint,
}: {
  sources: BusinessCitation[]
  endpoint: string
}) {
  const [token, setToken] = useState<string | null>(null)
  if (!sources.length) return null
  return (
    <div className="business-sources">
      <span className="eyebrow">业务依据</span>
      <div className="business-source-list">
        {sources.map((source, index) =>
          source.unavailable ? (
            <span className="muted" key={index}>
              来源已失效
            </span>
          ) : (
            <button
              className="business-source"
              key={source.token}
              onClick={() => setToken(source.token!)}
            >
              <FileText size={15} />
              <span>
                <strong>
                  {index + 1}. {source.employeeName} · {source.title}
                </strong>
                <small>
                  第 {source.revision} 版 · {dateLabel(source.at!)}
                  {source.location ? ` · ${source.location}` : ''}
                </small>
              </span>
            </button>
          ),
        )}
      </div>
      {token && <SourceView path={`${endpoint}/${token}`} onClose={() => setToken(null)} />}
    </div>
  )
}

function SourceView({ path, onClose }: { path: string; onClose: () => void }) {
  const { data, error, refresh } = useResource<BusinessSource>(path, 5000)
  const location = useLocation()
  const names: Record<string, string> = {
    title: '事项',
    summary: '进展',
    status: '状态',
    blocker: '阻碍',
    nextStep: '下一步',
    completed: '已完成',
    ongoing: '进行中',
    blockers: '阻碍',
    next: '下一步',
    text: '原始文字',
    transcript: '语音文字',
  }
  const statuses: Record<string, string> = {
    blocked: '有阻碍',
    done: '已完成',
    in_progress: '进行中',
  }
  return (
    <Modal title="业务来源" onClose={onClose}>
      <ErrorNotice retry={refresh}>{error}</ErrorNotice>
      {data && (
        <div className="business-source-detail">
          <header>
            <h3>{data.title}</h3>
            <p className="muted">
              {data.employeeName} · 第 {data.revision} 版 · {dateLabel(data.at!)}
              {data.employeeActive === false ? ' · 已停用员工' : ''}
            </p>
          </header>
          {data.currentRevision && data.currentRevision !== data.revision && (
            <p className="notice">
              这是回答使用的历史版本，当前已更新至第 {data.currentRevision} 版。
            </p>
          )}
          {data.period && (
            <p className="muted">
              报告周期：{data.period} 至 {data.periodEnd}
            </p>
          )}
          {data.location && <p className="muted">{data.location}</p>}
          <dl>
            {Object.entries(data.content)
              .filter(([, value]) => value)
              .map(([key, value]) => (
                <div key={key}>
                  <dt>{names[key] ?? key}</dt>
                  <dd className="preserve">
                    {key === 'status' ? (statuses[value] ?? value) : value}
                  </dd>
                </div>
              ))}
          </dl>
          {data.objectType && ['work', 'report'].includes(data.objectType) && (
            <Link
              className="text-button"
              to={`/${data.objectType === 'work' ? 'work' : 'reports'}/${data.objectId}`}
              state={detailState(location)}
              onClick={onClose}
            >
              <Link2 size={15} />
              查看当前{data.objectType === 'work' ? '工作' : '报告'}
            </Link>
          )}
        </div>
      )}
    </Modal>
  )
}

export function BusinessReply({
  text,
  sources,
  endpoint,
}: {
  text: string
  sources: BusinessCitation[]
  endpoint: string
}) {
  const [token, setToken] = useState<string | null>(null)
  return (
    <>
      <Markdown
        text={text}
        renderBusinessCitation={(index) => {
          const source = sources[index - 1]
          return source?.token && !source.unavailable ? (
            <button
              className="business-inline-citation"
              aria-label={`查看来源 ${index}`}
              onClick={() => setToken(source.token!)}
            >
              〔来源 {index}〕
            </button>
          ) : (
            `〔来源${index}〕`
          )
        }}
      />
      <BusinessSources sources={sources} endpoint={endpoint} />
      {token && <SourceView path={`${endpoint}/${token}`} onClose={() => setToken(null)} />}
    </>
  )
}
