import type { CompanyService } from '@paa/api-contracts'
import type { Listing } from '@web/features/model-services/types'
import type { ServiceDraft } from '@web/features/model-services/utils/service-drafts'
import { serviceHasChanges } from '@web/features/model-services/utils/service-drafts'
import { ChevronRight, Cpu, Plus } from 'lucide-react'

export function ServiceList({
  allServices,
  resource,
  createService,
  drafts,
  services,
  keys,
  usesFor,
  select,
}: {
  allServices: (CompanyService | ServiceDraft)[]
  resource: { data: Listing | null; error: string | Error; refresh: () => void }
  createService: () => void
  drafts: Record<string, ServiceDraft>
  services: CompanyService[]
  keys: Record<string, string>
  usesFor: (serviceId: string, modelId?: string) => string[]
  select: (id: string | null) => void
}) {
  return (
    <section className="sectioned-panel service-overview" aria-label="模型服务列表">
      <header className="service-overview-heading">
        <h3>
          已添加的服务 <span className="muted">{allServices.length}</span>
        </h3>
        <span className="muted">选择服务管理连接与模型</span>
      </header>
      {!resource.data && !resource.error && <p className="model-placeholder">正在读取服务…</p>}
      {resource.data && !allServices.length && (
        <div className="model-placeholder">
          <Cpu size={32} />
          <h3>添加你的第一个模型服务</h3>
          <p>填写服务地址和密钥，添加模型后分配给各项功能。</p>
          <button className="primary" onClick={createService}>
            <Plus size={16} /> 添加服务
          </button>
        </div>
      )}
      {allServices.map((service) => {
        const current = drafts[service.id] ?? service
        const changed =
          serviceHasChanges(
            current,
            services.find((item) => item.id === service.id),
          ) || !!keys[service.id]
        const purposes = usesFor(service.id)
        return (
          <button
            className="service-overview-row"
            key={service.id}
            onClick={() => select(service.id)}
          >
            <span className="service-symbol">
              <Cpu size={21} />
            </span>
            <span className="service-overview-name">
              <strong>{current.name || '新服务'}</strong>
              <small>{current.baseUrl || '待填写连接信息'}</small>
            </span>
            <span className="service-overview-meta">
              <span>
                {current.models.length} 个模型{changed ? ' · 未保存' : ''}
              </span>
              <small>{purposes.length ? purposes.join(' · ') : '未分配用途'}</small>
            </span>
            <ChevronRight size={17} />
          </button>
        )
      })}
    </section>
  )
}
