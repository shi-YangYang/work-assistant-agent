import utilitiesStyles from '../../../styles/utilities.module.css'
import layoutStyles from '../../../styles/layout.module.css'
import modelServicesStyles from '../styles/model-services.module.css'
import type { CompanyModel } from '@paa/api-contracts'
import { BusyButton } from '@web/components/BusyButton'
import { PanelSection } from '@web/components/PanelSection'
import type { ServiceDraft } from '@web/features/model-services/utils/service-drafts'
import { matchModelProtocol } from '@web/features/model-services/utils/service-presets'
import { Cpu, FlaskConical, Plus, Search, SlidersHorizontal } from 'lucide-react'

export function ServiceModelLibrary({
  draft,
  busy,
  connectionReady,
  usesFor,
  onAdd,
  onConfigure,
  onTest,
}: {
  draft: ServiceDraft
  busy: string
  connectionReady: boolean
  usesFor: (serviceId: string, modelId?: string) => string[]
  onAdd: (mode: 'catalog' | 'manual') => void
  onConfigure: (model: CompanyModel) => void
  onTest: (model: CompanyModel) => void
}) {
  return (
    <PanelSection compactStatus title="可用模型" status={`${draft.models.length} / 32`} defaultOpen>
      <div className={modelServicesStyles['model-library-toolbar']}>
        <span className={`${utilitiesStyles['muted']} ${modelServicesStyles['slot-muted']}`}>
          选择模型进行设置或测试
        </span>
        <div
          className={`${layoutStyles['card-actions']} ${modelServicesStyles['slot-card-actions']}`}
        >
          <BusyButton
            busy={busy === 'models'}
            disabled={!!busy || !connectionReady}
            onClick={() => onAdd('catalog')}
          >
            <Search size={15} /> 获取模型
          </BusyButton>
          <button disabled={draft.models.length >= 32 || !!busy} onClick={() => onAdd('manual')}>
            <Plus size={15} /> 手动添加
          </button>
        </div>
      </div>
      {!draft.models.length && (
        <div className={modelServicesStyles['model-library-empty']}>
          <Cpu size={24} />
          <p>还没有添加模型</p>
          <small>
            {connectionReady
              ? '获取服务提供的模型列表，或手动输入模型 ID。'
              : '先填写服务地址和密钥，也可以手动添加模型。'}
          </small>
        </div>
      )}
      <div className={modelServicesStyles['model-library']} role="list" aria-label="已添加模型">
        {draft.models.map((item) => {
          const unresolved =
            item.protocolMode === 'auto' && !matchModelProtocol(draft.baseUrl, item.model).protocol
          const purposes = usesFor(draft.id, item.id)
          return (
            <div className={modelServicesStyles['model-library-row']} role="listitem" key={item.id}>
              <div className={modelServicesStyles['model-library-info']}>
                <strong>{item.model || '未填写模型 ID'}</strong>
                <small
                  className={
                    unresolved
                      ? utilitiesStyles['error-text'] + ' ' + modelServicesStyles['slot-error-text']
                      : ''
                  }
                >
                  {unresolved
                    ? '需要选择接口协议'
                    : item.protocol === 'chat'
                      ? '聊天模型'
                      : '语音转写'}
                  {purposes.length ? ` · ${purposes.join('、')}` : ''}
                </small>
              </div>
              <div
                className={`${layoutStyles['card-actions']} ${modelServicesStyles['slot-card-actions']}`}
              >
                <button
                  disabled={!!busy}
                  aria-label={`设置 ${item.model}`}
                  onClick={() => onConfigure(item)}
                >
                  <SlidersHorizontal size={15} /> 设置
                </button>
                <button
                  disabled={!!busy || !connectionReady || unresolved}
                  aria-label={`测试 ${item.model}`}
                  onClick={() => onTest(item)}
                >
                  <FlaskConical size={15} /> 测试
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </PanelSection>
  )
}
