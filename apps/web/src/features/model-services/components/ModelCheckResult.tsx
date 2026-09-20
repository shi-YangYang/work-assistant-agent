import type { ModelCheck } from '@paa/api-contracts'
import { Modal } from '@web/components/Modal'
import { dateLabel } from '@web/utils/date'
import { Check } from 'lucide-react'
import type * as React from 'react'

export function ModelCheckResult({
  checkOpen,
  check,
  setCheckOpen,
}: {
  checkOpen: boolean
  check: ModelCheck | null
  setCheckOpen: React.Dispatch<React.SetStateAction<boolean>>
}) {
  return (
    <>
      {checkOpen && check && (
        <Modal title="模型测试结果" onClose={() => setCheckOpen(false)}>
          <section className="model-check">
            <p className="wrap-anywhere">
              {check.service} · {check.model}
            </p>
            <small>
              {dateLabel(check.time)} · {check.elapsedMs} ms
            </small>
            {check.checks.map((item) => (
              <p key={item.name} className={item.state === 'failed' ? 'error-text' : ''}>
                {item.state === 'passed' ? <Check size={15} /> : null} {item.name}：
                {{ passed: '通过', failed: '失败', untested: '未测试' }[item.state]}
                {item.message && `，${item.message}`}
              </p>
            ))}
            <small>
              {check.usage
                ? Object.entries(check.usage)
                    .map(([name, count]) => `${name}：${count}`)
                    .join(' · ')
                : '服务未返回用量。'}
            </small>
          </section>
          <div className="form-actions">
            <button onClick={() => setCheckOpen(false)}>关闭</button>
          </div>
        </Modal>
      )}
    </>
  )
}
