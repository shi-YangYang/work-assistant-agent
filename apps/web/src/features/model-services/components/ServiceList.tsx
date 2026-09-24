import layoutStyles from '../../../styles/layout.module.css'
import utilitiesStyles from '../../../styles/utilities.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import modelServicesStyles from '../styles/model-services.module.css'
import type { CompanyService } from '@paa/api-contracts'
import type { Listing } from '@web/features/model-services/types'
import type { ServiceDraft } from '@web/features/model-services/utils/service-drafts'
import { serviceHasChanges } from '@web/features/model-services/utils/service-drafts'
import { ChevronRight, Cpu, Plus } from 'lucide-react'

export function ServiceList({
  compact = false,
  disabled = false,
  selectedId,
  allServices,
  resource,
  createService,
  drafts,
  services,
  keys,
  usesFor,
  select,
}: {
  compact?: boolean
  disabled?: boolean
  selectedId?: string
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
    <section
      className={`${layoutStyles['sectioned-panel']} ${compact ? modelServicesStyles['service-sidebar'] : ''}`}
      aria-label="模型服务列表"
    >
      <header className={modelServicesStyles['service-overview-heading']}>
        <h3>
          已添加的服务{' '}
          <span className={`${utilitiesStyles['muted']} ${modelServicesStyles['slot-muted']}`}>
            {allServices.length}
          </span>
        </h3>
        <span className={`${utilitiesStyles['muted']} ${modelServicesStyles['slot-muted']}`}>
          选择服务管理连接与模型
        </span>
      </header>
      {!resource.data && !resource.error && (
        <p className={modelServicesStyles['model-placeholder']}>正在读取服务…</p>
      )}
      {resource.data && !allServices.length && !compact && (
        <div className={modelServicesStyles['model-placeholder']}>
          <Cpu size={32} />
          <h3>添加你的第一个模型服务</h3>
          <p>填写服务地址和密钥，添加模型后分配给各项功能。</p>
          <button
            className={`${controlsStyles['primary']} ${modelServicesStyles['slot-primary']}`}
            disabled={disabled}
            onClick={createService}
          >
            <Plus size={16} /> 添加服务
          </button>
        </div>
      )}
      {resource.data && !allServices.length && compact && (
        <p className={modelServicesStyles['service-empty']}>还没有模型服务</p>
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
            className={modelServicesStyles['service-overview-row']}
            key={service.id}
            data-selected={selectedId === service.id}
            aria-pressed={selectedId === service.id}
            disabled={disabled}
            onClick={() => select(service.id)}
          >
            <span className={modelServicesStyles['service-symbol']}>
              <Cpu size={21} />
            </span>
            <span className={modelServicesStyles['service-overview-name']}>
              <strong title={current.baseUrl}>{current.name || '新服务'}</strong>
              <small>
                {compact
                  ? `${current.models.length} 个模型${changed ? ' · 未保存' : ''}`
                  : current.baseUrl || '待填写连接信息'}
              </small>
            </span>
            {!compact && (
              <span className={modelServicesStyles['service-overview-meta']}>
                <span>
                  {current.models.length} 个模型{changed ? ' · 未保存' : ''}
                </span>
                <small>{purposes.length ? purposes.join(' · ') : '未分配用途'}</small>
              </span>
            )}
            <ChevronRight size={17} />
          </button>
        )
      })}
    </section>
  )
}
