import { useEffect, useRef, useState } from 'react'
import { Download, Trash2, Check, ChevronDown } from 'lucide-react'
import type { ModelState, TranscriptionLanguage, ModelEntry } from '../shared/contracts'
import benchmarks from '../shared/local-model-benchmarks.json'

export const languageNames: Record<TranscriptionLanguage, string> = {
  zh: '中文',
  en: '英文',
  mixed: '中英混合',
}
export const bytesLabel = (bytes: number): string =>
  bytes >= 1e9 ? `${(bytes / 1e9).toFixed(2)} GB` : `${Math.ceil(bytes / 1e6)} MB`
type Measurement = { errorRate: number; peakRssBytes: number }
type Evidence = {
  measuredAt?: string
  environment?: {
    hardware?: string
    os?: string
    engine?: string
    computeType?: string
    threads?: number
    beam?: number
  }
  groups?: Record<
    string,
    {
      metric?: string
      sampleCount?: number
      audioSeconds?: number
      source?: string
      attribution?: string
      license?: string
      revision?: string
      normalization?: unknown
    }
  >
  models?: Record<
    string,
    {
      revision?: string
      languages?: Record<string, Measurement | null>
      missingReasons?: Record<string, string>
    }
  >
}

function ModelEvidence({ model }: { model: ModelEntry }): React.JSX.Element {
  const data = benchmarks as unknown as Evidence
  const measured = data.models?.[model.id]
  const hasMeasurements = Object.keys(measured?.languages ?? {}).length > 0
  return (
    <details className="local-model-evidence">
      <summary>
        识别效果与模型信息 <ChevronDown size={14} />
      </summary>
      <div className="local-model-evidence-body">
        <div className="model-quality-grid">
          {(Object.keys(languageNames) as TranscriptionLanguage[]).map((language) => {
            const value =
              measured?.revision === model.revision ? measured.languages?.[language] : null
            const reason = measured?.missingReasons?.[language]
            return (
              <div key={language}>
                <strong>{languageNames[language]}</strong>
                <dl>
                  <div>
                    <dt>
                      {language === 'zh'
                        ? '字错率 CER'
                        : language === 'en'
                          ? '词错率 WER'
                          : '混合错误率 MER'}
                    </dt>
                    <dd>
                      {value
                        ? `${(value.errorRate * 100).toFixed(2)}%`
                        : reason
                          ? '测试未完成'
                          : '未实测'}
                    </dd>
                  </div>
                  <div>
                    <dt>峰值内存</dt>
                    <dd>
                      {value ? bytesLabel(value.peakRssBytes) : reason ? '测试未完成' : '未实测'}
                    </dd>
                  </div>
                </dl>
                {reason && <p>{reason}</p>}
              </div>
            )
          })}
        </div>
        <p>
          错误率越低越好；三种语言的计分单位不同。内存为基准转写进程峰值，含模型加载、解码与评分开销；不等于文件体积或整应用内存。
        </p>
        {hasMeasurements && (
          <p>
            本应用参考机实测 ·{' '}
            {data.measuredAt ? new Date(data.measuredAt).toLocaleDateString('zh-CN') : ''} ·{' '}
            {data.environment?.hardware} · {data.environment?.os} · CPU INT8
          </p>
        )}
        {hasMeasurements && (
          <dl className="model-test-conditions">
            {Object.entries(data.groups ?? {}).map(([language, group]) => (
              <div key={language}>
                <dt>{languageNames[language as TranscriptionLanguage]}</dt>
                <dd>
                  {group.sampleCount} 段 · 约 {Math.round(group.audioSeconds ?? 0)} 秒 ·{' '}
                  {group.attribution ?? group.source} · {group.license}
                </dd>
              </div>
            ))}
          </dl>
        )}
        <p>
          来源：{model.source} · {model.license} 许可
        </p>
        <p className="model-revision">固定版本：{model.revision}</p>
      </div>
    </details>
  )
}

export function ModelSettings({
  model,
  refresh,
}: {
  model: ModelState | null
  refresh: () => void
}): React.JSX.Element {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [removing, setRemoving] = useState<ModelEntry | null>(null)
  const dialog = useRef<HTMLDialogElement>(null)
  const trigger = useRef<HTMLElement | null>(null)
  useEffect(() => {
    if (removing) dialog.current?.showModal()
  }, [removing])
  async function act(
    action: 'download' | 'cancel' | 'configure' | 'remove',
    id: string,
    language?: TranscriptionLanguage,
  ): Promise<void> {
    setBusy(true)
    setError('')
    try {
      const result = await window.paa.manageTranscriptionModel(action, id, language)
      if (!result.ok) setError(result.message)
      else if (action === 'remove') close()
      refresh()
    } catch {
      setError('无法确认模型状态，请稍后重试。')
    } finally {
      setBusy(false)
    }
  }
  function close(): void {
    dialog.current?.close()
    setRemoving(null)
    trigger.current?.focus()
  }
  return (
    <section className="local-model-library" aria-label="本地转写模型">
      <section className="settings-card local-model-defaults">
        <div>
          <h2>默认转写设置</h2>
          <p>用于之后新建的转写任务</p>
        </div>
        <label>
          默认模型
          <select
            aria-label="默认转写模型"
            value={model?.defaultModel ?? 'small'}
            disabled={!model || busy}
            onChange={(event) => void act('configure', event.target.value, model?.language ?? 'zh')}
          >
            {(model?.models ?? []).map((item) => (
              <option
                key={item.id}
                value={item.id}
                disabled={item.state !== 'ready' && !item.default}
              >
                {item.name}
                {item.state !== 'ready' ? '（未就绪）' : ''}
              </option>
            ))}
          </select>
        </label>
        <label>
          识别语言
          <select
            aria-label="识别语言"
            value={model?.language ?? 'zh'}
            disabled={!model || busy}
            onChange={(event) =>
              void act(
                'configure',
                model?.defaultModel ?? 'small',
                event.target.value as TranscriptionLanguage,
              )
            }
          >
            {Object.entries(languageNames).map(([value, name]) => (
              <option key={value} value={value}>
                {name}
              </option>
            ))}
          </select>
        </label>
      </section>
      {error && (
        <p className="audio-warning" role="alert">
          {error}
        </p>
      )}
      <div className="local-model-list">
        {(model?.models ?? []).map((item) => {
          const preparing = item.state === 'downloading' || item.state === 'verifying'
          return (
            <article className="settings-card local-model-item" key={item.id}>
              <div className="local-model-row">
                <div className="local-model-name">
                  <h3>{item.name}</h3>
                  {item.default && <span className="status-badge">默认</span>}
                  <span className="local-model-size">{item.parameters}M 参数</span>
                </div>
                <div className="local-model-actions">
                  {item.state === 'ready' ? (
                    <>
                      <span className="local-model-ready">
                        <Check size={15} />
                        已下载
                      </span>
                      {!item.default && (
                        <button
                          className="secondary-button"
                          disabled={busy}
                          onClick={() => void act('configure', item.id, model?.language)}
                        >
                          设为默认
                        </button>
                      )}
                    </>
                  ) : (
                    <button
                      className="secondary-button"
                      disabled={
                        busy ||
                        (!!model?.preparingModel && model.preparingModel !== item.id) ||
                        (item.state === 'verifying' && !model?.preparingModel)
                      }
                      onClick={() => void act(preparing ? 'cancel' : 'download', item.id)}
                    >
                      <Download size={15} />
                      {preparing
                        ? item.state === 'verifying' && !model?.preparingModel
                          ? '检查文件中'
                          : '取消准备'
                        : item.state === 'error'
                          ? '重试下载'
                          : '下载模型'}
                    </button>
                  )}
                  {item.occupiedBytes > 0 && !preparing && (
                    <button
                      className="icon-button"
                      aria-label={`删除 ${item.name}`}
                      title={item.deleteBlockedReason ?? '删除下载文件'}
                      disabled={busy || !!item.deleteBlockedReason}
                      onClick={() => {
                        trigger.current = document.activeElement as HTMLElement
                        setRemoving(item)
                      }}
                    >
                      <Trash2 size={16} />
                    </button>
                  )}
                </div>
              </div>
              <p className="local-model-description">{item.description}</p>
              <div className="local-model-meta">
                <span>下载 {bytesLabel(item.totalBytes)}</span>
                <span>已占用 {bytesLabel(item.occupiedBytes)}</span>
                {item.state !== 'ready' && <span>需预留 {bytesLabel(item.requiredBytes)}</span>}
              </div>
              {preparing && (
                <div className="model-progress">
                  <progress
                    aria-label={`${item.name} 下载进度`}
                    value={item.downloadedBytes}
                    max={item.totalBytes}
                  />
                  <span>
                    {item.state === 'verifying'
                      ? '正在校验与准备，转写繁忙时将等待空闲'
                      : `${bytesLabel(item.downloadedBytes)} / ${bytesLabel(item.totalBytes)}`}
                  </span>
                </div>
              )}
              {item.error && (
                <p className="audio-warning" role="alert">
                  {item.error}
                </p>
              )}
              <ModelEvidence model={item} />
            </article>
          )
        })}
      </div>
      {removing && (
        <dialog
          ref={dialog}
          className="library-dialog"
          onCancel={(event) => {
            event.preventDefault()
            if (!busy) close()
          }}
        >
          <h2>删除 {removing.name}？</h2>
          <p>将释放 {bytesLabel(removing.occupiedBytes)} 空间。会议录音与文字记录会保留。</p>
          <div className="button-row">
            <button className="secondary-button" disabled={busy} onClick={close}>
              取消
            </button>
            <button
              className="primary-button delete-button"
              disabled={busy}
              onClick={() => void act('remove', removing.id)}
            >
              删除下载文件
            </button>
          </div>
        </dialog>
      )}
    </section>
  )
}
