import layoutStyles from '../../../styles/layout.module.css'
import controlsStyles from '../../../styles/controls.module.css'
import utilitiesStyles from '../../../styles/utilities.module.css'
import modelServicesStyles from '../styles/model-services.module.css'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Modal } from '@web/components/Modal'
import type { ServiceDraft } from '@web/features/model-services/utils/service-drafts'
import { Search } from 'lucide-react'
import type * as React from 'react'
import { useState } from 'react'

export function ModelPicker({
  picker,
  draft,
  busy,
  setPicker,
  addModels,
  error,
  catalog,
  setError,
}: {
  picker: 'catalog' | 'manual' | null
  draft: ServiceDraft | undefined
  busy: string
  setPicker: React.Dispatch<React.SetStateAction<'catalog' | 'manual' | null>>
  addModels: (ids: string[]) => void
  error: string | Error
  catalog: { models: string[]; source: string; truncated: boolean } | null
  setError: React.Dispatch<React.SetStateAction<string | Error>>
}) {
  const [query, setQuery] = useState('')
  const [pickedModels, setPickedModels] = useState<string[]>([])
  const [manualModel, setManualModel] = useState('')
  return (
    <>
      {picker && draft && (
        <Modal
          title={picker === 'catalog' ? '添加可用模型' : '手动添加模型'}
          className={modelServicesStyles['model-picker-dialog']}
          onClose={() => {
            if (!busy) setPicker(null)
          }}
        >
          {picker === 'manual' ? (
            <form
              onSubmit={(event) => {
                event.preventDefault()
                addModels([manualModel])
              }}
            >
              <label>
                模型 ID
                <input
                  autoFocus
                  required
                  maxLength={200}
                  placeholder="例如 qwen-plus"
                  value={manualModel}
                  onChange={(event) => setManualModel(event.target.value)}
                />
              </label>
              <ErrorNotice>{error}</ErrorNotice>
              <div
                className={`${layoutStyles['form-actions']} ${modelServicesStyles['slot-form-actions']}`}
              >
                <button type="button" onClick={() => setPicker(null)}>
                  取消
                </button>
                <button
                  className={`${controlsStyles['primary']} ${modelServicesStyles['slot-primary']}`}
                  disabled={!manualModel.trim()}
                >
                  添加模型
                </button>
              </div>
            </form>
          ) : (
            <>
              {busy === 'models' && <p role="status">正在获取模型列表…</p>}
              <ErrorNotice>{error}</ErrorNotice>
              {catalog && (
                <>
                  <label className={modelServicesStyles['model-picker-search']}>
                    <Search size={16} />
                    <input
                      aria-label="搜索可用模型"
                      placeholder="搜索模型 ID"
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                    />
                  </label>
                  <div
                    className={modelServicesStyles['model-picker-list']}
                    aria-label="可用模型目录"
                  >
                    {catalog.models
                      .filter((id) => id.toLowerCase().includes(query.toLowerCase()))
                      .map((id) => {
                        const added = draft.models.some((item) => item.model === id)
                        const checked = pickedModels.includes(id)
                        return (
                          <label key={id}>
                            <input
                              type="checkbox"
                              checked={added || checked}
                              disabled={
                                added ||
                                (!checked && pickedModels.length + draft.models.length >= 32)
                              }
                              onChange={(event) =>
                                setPickedModels((previous) =>
                                  event.target.checked
                                    ? [...previous, id]
                                    : previous.filter((value) => value !== id),
                                )
                              }
                            />
                            <span>{id}</span>
                            {added && <small>已添加</small>}
                          </label>
                        )
                      })}
                    {!catalog.models.some((id) =>
                      id.toLowerCase().includes(query.toLowerCase()),
                    ) && (
                      <p
                        className={`${utilitiesStyles['muted']} ${modelServicesStyles['slot-muted']}`}
                      >
                        没有找到匹配的模型，可手动添加。
                      </p>
                    )}
                  </div>
                  {catalog.truncated && (
                    <small
                      className={`${utilitiesStyles['muted']} ${modelServicesStyles['slot-muted']}`}
                    >
                      列表未完全返回，可手动输入其它模型 ID。
                    </small>
                  )}
                </>
              )}
              <div
                className={`${layoutStyles['form-actions']} ${modelServicesStyles['slot-form-actions']} ${modelServicesStyles['model-picker-actions']}`}
              >
                <span
                  className={`${utilitiesStyles['muted']} ${modelServicesStyles['slot-muted']}`}
                >
                  已选 {pickedModels.length} 个
                </span>
                <button
                  disabled={!!busy}
                  onClick={() => {
                    setManualModel(query)
                    setError('')
                    setPicker('manual')
                  }}
                >
                  手动输入
                </button>
                <button
                  className={`${controlsStyles['primary']} ${modelServicesStyles['slot-primary']}`}
                  disabled={!!busy || !pickedModels.length}
                  onClick={() => addModels(pickedModels)}
                >
                  添加所选模型
                </button>
              </div>
            </>
          )}
        </Modal>
      )}
    </>
  )
}
