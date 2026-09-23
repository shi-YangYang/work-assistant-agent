import layoutStyles from '../../../styles/layout.module.css'
import type { CompanyService } from '@paa/api-contracts'
import { BusyButton } from '@web/components/BusyButton'
import { ErrorNotice } from '@web/components/ErrorNotice'
import { Modal } from '@web/components/Modal'
import type { ServiceDraft } from '@web/features/model-services/utils/service-drafts'
import type * as React from 'react'
import type { Blocker } from 'react-router'

export function UnsavedKeysDialog({
  blocker,
  busy,
  keys,
  save,
  drafts,
  services,
  setKeys,
  error,
}: {
  blocker: Blocker
  busy: string
  keys: Record<string, string>
  save: (target?: ServiceDraft | undefined, assign?: boolean) => Promise<boolean>
  drafts: Record<string, ServiceDraft>
  services: CompanyService[]
  setKeys: React.Dispatch<React.SetStateAction<Record<string, string>>>
  error: string | Error
}) {
  return (
    <>
      {blocker.state === 'blocked' && (
        <Modal title="密钥尚未保存" onClose={() => blocker.reset()}>
          <p>离开会丢弃尚未保存的密钥，普通编辑草稿仍保留。</p>
          <div className={layoutStyles['card-actions']}>
            <BusyButton
              busy={busy === 'save'}
              onClick={async () => {
                for (const id of Object.keys(keys).filter((id) => keys[id])) {
                  if (!(await save(drafts[id] ?? services.find((s) => s.id === id)))) return
                }
                blocker.proceed()
              }}
            >
              保存后离开
            </BusyButton>
            <button
              onClick={() => {
                setKeys({})
                blocker.proceed()
              }}
            >
              丢弃密钥并离开
            </button>
            <button onClick={() => blocker.reset()}>继续编辑</button>
          </div>
          <ErrorNotice>{error}</ErrorNotice>
        </Modal>
      )}
    </>
  )
}
