import utilitiesStyles from '../../../styles/utilities.module.css'
import layoutStyles from '../../../styles/layout.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import type { CompanyModel } from '@paa/api-contracts'
import { BusyButton } from '@web/components/BusyButton'
import { Modal } from '@web/components/Modal'
import type { Purpose } from '@web/features/model-services/types'
import { purposeNames } from '@web/features/model-services/types'
import type { ServiceDraft } from '@web/features/model-services/utils/service-drafts'
import type * as React from 'react'

export function ModelTestDialog({
  testOpen,
  draft,
  busy,
  setTestOpen,
  model,
  testPurpose,
  setTestPurpose,
  request,
}: {
  testOpen: boolean
  draft: ServiceDraft | undefined
  busy: string
  setTestOpen: React.Dispatch<React.SetStateAction<boolean>>
  model: CompanyModel | undefined
  testPurpose: Purpose
  setTestPurpose: React.Dispatch<React.SetStateAction<Purpose>>
  request: (kind: 'models' | 'test') => Promise<void>
}) {
  return (
    <>
      {testOpen && draft && (
        <Modal
          title="测试模型配置"
          onClose={() => {
            if (!busy) setTestOpen(false)
          }}
        >
          <p className={utilitiesStyles['wrap-anywhere']}>
            接收服务：{draft.name}（{draft.baseUrl}）
          </p>
          <p className={utilitiesStyles['wrap-anywhere']}>模型：{model?.model || '未填写'}</p>
          <label>
            检测用途
            <select
              disabled={!!busy}
              value={testPurpose}
              onChange={(e) => setTestPurpose(e.target.value as Purpose)}
            >
              {(model?.protocol === 'chat' ? ['assistant', 'report'] : ['asr']).map((p) => (
                <option key={p} value={p}>
                  {purposeNames[p as Purpose]}
                </option>
              ))}
            </select>
          </label>
          <p>
            会发送固定的
            {testPurpose === 'asr'
              ? '中文短语音'
              : testPurpose === 'assistant'
                ? '文字、图片与工具测试样本'
                : '文字与工具测试样本'}
            ，可能产生服务费用，不使用员工资料。
          </p>
          <div className={layoutStyles['form-actions']}>
            <button disabled={!!busy} onClick={() => setTestOpen(false)}>
              取消
            </button>
            <BusyButton
              className={controlsStyles['primary']}
              busy={busy === 'test'}
              disabled={!!busy}
              onClick={() => void request('test')}
            >
              开始测试
            </BusyButton>
          </div>
        </Modal>
      )}
    </>
  )
}
