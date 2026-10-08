import type { CompanyModel } from '@paa/api-contracts'
import { useId, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { validateCompanyParameters, validateReasoning } from '../../utils/service-drafts'
import styles from './ReasoningSettings.module.css'

export function ReasoningSettings({
  model,
  updateModel,
  onValidityChange,
}: {
  model: CompanyModel
  updateModel: (model: CompanyModel) => void
  onValidityChange: (invalid: boolean) => void
}) {
  const inputId = useId()
  const inputRef = useRef<HTMLInputElement>(null)
  const [text, setText] = useState('')
  const [entryError, setEntryError] = useState('')
  const [advanced, setAdvanced] = useState(
    JSON.stringify(
      {
        parameters: model.parameters,
        parameterOverrides: model.reasoning.parameterOverrides ?? {},
      },
      null,
      2,
    ),
  )
  const [advancedError, setAdvancedError] = useState('')
  let error = ''
  try {
    validateReasoning(model)
  } catch (issue) {
    error = (issue as Error).message
  }
  const updateEfforts = (efforts: string[]) => {
    const initial = efforts.includes(model.reasoning.initial ?? '')
      ? model.reasoning.initial
      : (efforts[0] ?? null)
    const parameterOverrides = Object.fromEntries(
      Object.entries(model.reasoning.parameterOverrides ?? {}).filter(([effort]) =>
        efforts.includes(effort),
      ),
    )
    updateModel({ ...model, reasoning: { efforts, initial, parameterOverrides } })
    if (!advancedError)
      setAdvanced(JSON.stringify({ parameters: model.parameters, parameterOverrides }, null, 2))
  }
  const addEffort = () => {
    const effort = text.trim()
    const message = !effort
      ? ''
      : !/^[a-z][a-z0-9_-]{0,31}$/.test(effort)
        ? '每次输入一个档位，例如 high；使用小写字母、数字、连字符或下划线。'
        : model.reasoning.efforts.includes(effort)
          ? `已添加 ${effort}，请勿重复。`
          : model.reasoning.efforts.length >= 16
            ? '最多添加 16 个档位。'
            : ''
    setEntryError(message)
    if (message) {
      onValidityChange(true)
      return
    }
    if (effort) updateEfforts([...model.reasoning.efforts, effort])
    setText('')
    onValidityChange(!!advancedError)
  }
  const fieldError = entryError || error
  return (
    <section className={styles.settings} aria-label="思考强度设置">
      <div className={styles.field}>
        <label htmlFor={inputId}>可选思考强度</label>
        <div className={styles.tagInput} data-invalid={!!fieldError}>
          {model.reasoning.efforts.map((effort) => (
            <span className={styles.tag} key={effort}>
              {effort}
              <button
                type="button"
                className={styles.tagRemove}
                aria-label={`删除强度 ${effort}`}
                onClick={() => {
                  updateEfforts(model.reasoning.efforts.filter((item) => item !== effort))
                  setEntryError('')
                  onValidityChange(!!advancedError || !!text.trim())
                  inputRef.current?.focus()
                }}
              >
                <X size={13} aria-hidden="true" />
              </button>
            </span>
          ))}
          <input
            ref={inputRef}
            id={inputId}
            value={text}
            placeholder="输入档位，按 Enter 添加"
            aria-invalid={!!fieldError}
            aria-describedby={`${inputId}-hint`}
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            enterKeyHint="done"
            onChange={(event) => {
              setText(event.target.value)
              setEntryError('')
              onValidityChange(!!advancedError || !!event.target.value.trim())
            }}
            onKeyDown={(event) => {
              if (
                event.key === 'Enter' &&
                !event.nativeEvent.isComposing &&
                event.keyCode !== 229
              ) {
                event.preventDefault()
                addEffort()
              }
            }}
          />
        </div>
        <small
          id={`${inputId}-hint`}
          className={fieldError ? styles.error : undefined}
          role={fieldError ? 'alert' : undefined}
        >
          {fieldError || '逐个添加此模型支持的档位，例如 high；不添加时由服务商决定。'}
        </small>
      </div>
      {model.reasoning.efforts.length > 0 && (
        <label>
          初始思考强度
          <select
            value={model.reasoning.initial ?? ''}
            onChange={(event) =>
              updateModel({
                ...model,
                reasoning: { ...model.reasoning, initial: event.target.value },
              })
            }
          >
            {[...new Set(model.reasoning.efforts)].map((effort) => (
              <option key={effort} value={effort}>
                {effort}
              </option>
            ))}
          </select>
        </label>
      )}
      <details>
        <summary>高级请求参数</summary>
        <label>
          服务商参数（JSON）
          <textarea
            aria-label="服务商参数（JSON）"
            value={advanced}
            aria-invalid={!!advancedError}
            onChange={(event) => {
              setAdvanced(event.target.value)
              try {
                const value = JSON.parse(event.target.value)
                if (
                  !value ||
                  typeof value !== 'object' ||
                  Array.isArray(value) ||
                  Object.keys(value).some(
                    (key) => !['parameters', 'parameterOverrides'].includes(key),
                  )
                )
                  throw new Error('只能填写 parameters 和 parameterOverrides。')
                validateCompanyParameters(value.parameters ?? {})
                const next = {
                  ...model,
                  parameters: value.parameters ?? {},
                  reasoning: {
                    ...model.reasoning,
                    parameterOverrides: value.parameterOverrides ?? {},
                  },
                }
                validateReasoning(next)
                updateModel(next)
                setAdvancedError('')
                onValidityChange(!!text.trim() || !!entryError)
              } catch (issue) {
                setAdvancedError((issue as Error).message)
                onValidityChange(true)
              }
            }}
          />
        </label>
        {advancedError ? (
          <small role="alert">{advancedError}</small>
        ) : (
          <small>
            普通档位无需填写。parameters 是基础参数，parameterOverrides
            仅用于特殊接口的完整参数覆盖。
          </small>
        )}
      </details>
    </section>
  )
}
