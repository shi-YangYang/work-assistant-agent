import { purposeNames, stateNames, number, duration } from './usage-display'
import { UsageTable } from './UsageTable'
import controlsStyles from '@web/styles/controls.module.css'
import { PageHeader } from '@web/components/layout/page-header/PageHeader'
import layoutStyles from '../../../../styles/layout.module.css'
import utilitiesStyles from '../../../../styles/utilities.module.css'
import styles from './ModelUsagePage.module.css'
import type { ModelUsage, UsageRecord } from '@paa/api-contracts'
import { ErrorNotice } from '@web/components/feedback/ErrorNotice'
import { Pagination } from '@web/components/actions/Pagination'
import { PeriodFilter } from '@web/components/forms/PeriodFilter'
import { modelUsagePath } from '@web/features/model-services/api/requests'
import { useCursorPage } from '@web/hooks/useCursorPage'
import { RefreshCw } from 'lucide-react'
import { useSearchParams } from 'react-router'

export function ModelUsagePage() {
  const [params] = useSearchParams()
  const query = new URLSearchParams(params)
  query.delete('after')
  const list = useCursorPage<UsageRecord, Omit<ModelUsage, 'items' | 'nextCursor'>>(
    modelUsagePath(query),
  )
  const data = list.data
  return (
    <div className={layoutStyles['settings-page']}>
      <PageHeader
        title="模型用量"
        actions={
          <button
            className={controlsStyles['icon-button']}
            aria-label="刷新模型用量"
            onClick={list.refresh}
          >
            <RefreshCw size={16} />
          </button>
        }
      />
      <div className={`${layoutStyles['filters']} ${styles['usage-filters']}`}>
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
      {!data && !list.error && <p className={utilitiesStyles['muted']}>正在读取调用记录…</p>}
      {data && (
        <>
          <div className={`${layoutStyles['metrics']} ${styles['usage-metrics']}`}>
            <div>
              <small>模型请求</small>
              <strong>{data.summary.calls}</strong>
            </div>
            <div>
              <small>请求成功率</small>
              <strong>
                {data.summary.successRate === null
                  ? '暂无'
                  : `${(data.summary.successRate * 100).toFixed(1)}%`}
              </strong>
              <small>
                已知结果 {(data.summary.states.succeeded ?? 0) + (data.summary.states.failed ?? 0)}{' '}
                次 · 未知 {data.summary.states.unknown ?? 0} 次
              </small>
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
          <div className={styles['usage-caption']}>
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
          <UsageTable items={data.items} />
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
