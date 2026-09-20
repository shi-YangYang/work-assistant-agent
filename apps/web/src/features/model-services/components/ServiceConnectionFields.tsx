import { PanelSection } from '@web/components/PanelSection'
import type { ServiceDraft } from '@web/features/model-services/utils/service-drafts'
import type { ServicePreset } from '@web/features/model-services/utils/service-presets'
import {
  detectServicePreset,
  servicePresets,
} from '@web/features/model-services/utils/service-presets'

export function ServiceConnectionFields({
  draft,
  busy,
  changeAddress,
  update,
  keyValue,
  onKeyChange,
}: {
  keyValue: string
  onKeyChange: (value: string) => void
  draft: ServiceDraft
  busy: string
  changeAddress: (baseUrl: string, providerPreset: ServicePreset, name?: string | undefined) => void
  update: (next: ServiceDraft) => void
}) {
  return (
    <PanelSection title="连接信息" status={draft.baseUrl || '待填写'} defaultOpen={!draft.revision}>
      <fieldset disabled={!!busy} aria-label="连接信息">
        <div className="field-grid connection-fields">
          <label>
            服务商预设
            <select
              value={draft.providerPreset ?? detectServicePreset(draft.baseUrl)}
              onChange={(e) => {
                const id = e.target.value as ServicePreset
                const preset = servicePresets[id]
                const defaultName =
                  draft.name === '新服务' ||
                  Object.values(servicePresets).some((p) => p.name === draft.name)
                changeAddress(
                  id === 'custom' ? draft.baseUrl : preset.baseUrl,
                  id,
                  id !== 'custom' && defaultName ? preset.name : draft.name,
                )
              }}
            >
              {Object.entries(servicePresets).map(([id, preset]) => (
                <option key={id} value={id}>
                  {preset.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            服务名称
            <input
              value={draft.name}
              maxLength={80}
              onChange={(e) => update({ ...draft, name: e.target.value })}
            />
          </label>
          <label className="full-field">
            Base URL
            <input
              value={draft.baseUrl}
              placeholder="https://api.example.com/v1"
              maxLength={2048}
              autoComplete="off"
              onChange={(e) => changeAddress(e.target.value, detectServicePreset(e.target.value))}
            />
          </label>
          <label className="full-field">
            API 密钥{' '}
            <span className="muted">
              {draft.hasKey ? '已设置；地址不变时留空保留' : '尚未设置'}
            </span>
            <input
              type="password"
              autoComplete="new-password"
              value={keyValue}
              maxLength={4096}
              placeholder={draft.hasKey ? '输入新密钥以替换' : '输入密钥'}
              onChange={(e) => onKeyChange(e.target.value)}
            />
          </label>
        </div>
      </fieldset>
    </PanelSection>
  )
}
