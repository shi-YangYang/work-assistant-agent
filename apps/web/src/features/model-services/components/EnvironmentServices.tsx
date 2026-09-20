import { BusyButton } from '@web/components/BusyButton'
import { importEnvironmentServices } from '@web/features/model-services/api/requests'
import type { Listing } from '@web/features/model-services/types'
import type * as React from 'react'

export function EnvironmentServices({
  resource,
  busy,
  setBusy,
  notify,
  handleError,
}: {
  resource: { data: Listing | null; error: string | Error; refresh: () => void }
  busy: string
  setBusy: React.Dispatch<React.SetStateAction<string>>
  notify: (message: string) => void
  handleError: (e: unknown) => void
}) {
  return (
    <>
      {resource.data?.routing.source === 'environment' && (
        <div className="notice model-environment">
          <details>
            <summary>当前使用服务器环境配置</summary>
            <p>
              助手：{resource.data.routing.environment?.assistant.model || '未设置'}；语音：
              {resource.data.routing.environment?.asr.model || '未设置'}。
            </p>
            <p className="wrap-anywhere">
              {resource.data.routing.environment?.assistant.baseUrl || '助手地址未设置'}
            </p>
            <p className="wrap-anywhere">
              {resource.data.routing.environment?.asr.baseUrl || '语音地址未设置'}
            </p>
          </details>
          <BusyButton
            busy={busy === 'import'}
            onClick={async () => {
              if (
                !window.confirm(
                  '导入当前环境服务并交由本页面管理？未配置的用途仍保留为空，此操作不会发起模型调用。',
                )
              )
                return
              setBusy('import')
              try {
                await importEnvironmentServices({})
                resource.refresh()
                notify('环境配置已导入')
              } catch (e) {
                handleError(e)
              } finally {
                setBusy('')
              }
            }}
          >
            导入配置
          </BusyButton>
        </div>
      )}
    </>
  )
}
