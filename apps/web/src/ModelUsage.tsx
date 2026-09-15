import { RefreshCw } from 'lucide-react'
import { useSearchParams } from 'react-router'
import type { ModelUsage, UsageRecord } from '@paa/api-contracts'
import { dateLabel } from './api'
import { useCursorPage } from './list-state'
import { Pagination, PeriodFilter } from './ListControls'
import { Empty, ErrorNotice } from './ui'

const purposeNames: Record<string, string> = {
  assistant: '工作助手',
  report: '报告生成',
  asr: '语音转写',
  admin_test: '配置测试',
}
const stateNames: Record<string, string> = {
  reserved: '尚未发出',
  running: '进行中',
  succeeded: '成功',
  failed: '失败',
  unknown: '结果未知',
  legacy: '历史未知',
  not_sent: '未发出',
}
const number = (value: number | null) => (value === null ? '未知' : value.toLocaleString('zh-CN'))
const duration = (value: number | null) =>
  value === null ? '未知' : `${(value / 1000).toFixed(2)} 秒`
export function ModelUsagePage() {
  const [params] = useSearchParams()
  const query = new URLSearchParams(params)
  query.delete('after')
  const list = useCursorPage<UsageRecord, Omit<ModelUsage, 'items' | 'nextCursor'>>(
    `/settings/model-usage?${query}`,
  )
  const data = list.data
  return (
    <div className="settings-page usage-page">
      <div className="page-heading">
        <h2>模型用量</h2>
        <button aria-label="刷新模型用量" onClick={list.refresh}>
          <RefreshCw size={16} />
        </button>
      </div>
      <div className="filters usage-filters">
        <PeriodFilter params={params} range={data?.range} change={list.filter} />
        <select
          aria-label="模型服务"
          value={params.get('service') || ''}
          onChange={(e) => list.filter({ service: e.target.value, model: '' })}
        >
          <option value="">全部服务</option>
          {data?.services.map((service) => (
            <option key={service.id} value={service.id}>
              {service.name}
            </option>
          ))}
        </select>
        <select
          aria-label="模型"
          value={params.get('model') || ''}
          onChange={(e) => list.filter({ model: e.target.value })}
        >
          <option value="">全部模型</option>
          {data?.models.map((model) => (
            <option key={model} value={model}>
              {model}
            </option>
          ))}
        </select>
        <select
          aria-label="调用用途"
          value={params.get('purpose') || ''}
          onChange={(e) => list.filter({ purpose: e.target.value })}
        >
          <option value="">全部用途</option>
          {Object.entries(purposeNames).map(([key, name]) => (
            <option key={key} value={key}>
              {name}
            </option>
          ))}
        </select>
      </div>
      <ErrorNotice retry={list.refresh}>{list.error}</ErrorNotice>
      {!data && !list.error && <p className="muted">正在读取调用记录…</p>}
      {data && (
        <>
          <div className="metrics usage-metrics">
            <div>
              <small>模型请求</small>
              <strong>{data.summary.calls}</strong>
            </div>
            <div>
              <small>请求成功率</small>
              <strong>
                {data.summary.successRate === null
                  ? '未知'
                  : `${(data.summary.successRate * 100).toFixed(1)}%`}
              </strong>
            </div>
            <div>
              <small>平均耗时</small>
              <strong>{duration(data.summary.averageMs)}</strong>
            </div>
            <div>
              <small>输入 Token</small>
              <strong>{data.summary.inputKnown ? number(data.summary.inputTokens) : '未知'}</strong>
              <small>
                {data.summary.inputKnown}/{data.summary.calls} 次有数据
              </small>
            </div>
            <div>
              <small>输出 Token</small>
              <strong>
                {data.summary.outputKnown ? number(data.summary.outputTokens) : '未知'}
              </strong>
              <small>
                {data.summary.outputKnown}/{data.summary.calls} 次有数据
              </small>
            </div>
          </div>
          <div className="usage-caption">
            <span>成功率仅统计已有明确请求结果的调用，不代表业务保存成功。</span>
            <span>
              {Object.entries(data.summary.states)
                .filter(([, count]) => count > 0)
                .map(([state, count]) => `${stateNames[state]} ${count}`)
                .join(' · ') || '本期暂无记录'}
            </span>
            <span>
              耗时覆盖 {data.summary.durationKnown}/{data.summary.calls}{' '}
              次；历史未知记录不计入请求总数。
            </span>
          </div>
          {data.items.length ? (
            <div className="usage-table-wrap">
              <table className="usage-table">
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>服务 / 模型</th>
                    <th>用途</th>
                    <th>结果</th>
                    <th>耗时</th>
                    <th>输入 / 输出 Token</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((row) => (
                    <tr key={row.id}>
                      <td>{dateLabel(row.createdAt)}</td>
                      <td>
                        <span>
                          {row.service ||
                            (row.purpose === 'admin_test' ? '未保存配置' : '历史未知')}
                        </span>
                        <small>{row.model || '历史未知'}</small>
                      </td>
                      <td>{purposeNames[row.purpose] || '历史未知'}</td>
                      <td>
                        <span className={`usage-state ${row.state}`}>
                          {stateNames[row.state] || '未知'}
                        </span>
                        {row.error && <small>{row.error}</small>}
                      </td>
                      <td>{duration(row.elapsedMs)}</td>
                      <td>
                        {number(row.inputTokens)} / {number(row.outputTokens)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty title="本期没有符合条件的调用" />
          )}
          <Pagination
            page={list.page}
            hasNext={!!data.nextCursor}
            previous={list.previous}
            next={list.next}
          />
        </>
      )}
    </div>
  )
}
