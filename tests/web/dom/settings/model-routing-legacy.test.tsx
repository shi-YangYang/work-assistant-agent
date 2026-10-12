// @vitest-environment jsdom
import type { ModelRouting } from '@paa/api-contracts'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { Routing } from '../../../../apps/web/src/features/model-services/components/Routing'
import {
  readModelRouting,
  saveModelRouting,
} from '../../../../apps/web/src/features/model-services/api/requests'
import { createVault, TestWorkspace } from '../helpers'
import { newModel } from '../../../../apps/web/src/features/model-services/utils/service-drafts'

vi.mock('@web/features/model-services/api/requests', () => ({
  readModelRouting: vi.fn(),
  saveModelRouting: vi.fn(),
}))
afterEach(cleanup)

it('assigns models without a separate streaming override', async () => {
  const vault = createVault()
  const current = {
    assistant: null,
    report: 'follow',
    asr: null,
    revision: 4,
    source: 'database',
    environment: null,
  } as ModelRouting
  const model = { ...newModel('chat'), id: 'model', streaming: false }
  render(
    <TestWorkspace vault={vault}>
      <Routing
        services={[
          {
            id: 'service',
            name: '服务',
            baseUrl: 'https://example.com',
            models: [model],
            revision: 1,
            hasKey: true,
            updatedAt: '',
          },
        ]}
        initial={current}
        refresh={vi.fn()}
      />
    </TestWorkspace>,
  )
  fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: 'service/model' } })
  expect(screen.queryByRole('checkbox', { name: '使用流式接口' })).toBeNull()
  expect((vault.getSnapshot().modelRouting as ModelRouting).assistant).toEqual({
    serviceId: 'service',
    modelId: 'model',
  })
})

it('keeps an obsolete routing draft until explicit reload succeeds without writing server configuration', async () => {
  const vault = createVault()
  const old = {
    assistant: { serviceId: 's', modelId: 'm', presetId: 'private', streaming: false },
    report: 'follow',
    asr: null,
    revision: 1,
  }
  const current = {
    assistant: null,
    report: 'follow',
    asr: null,
    revision: 4,
    source: 'database',
    environment: null,
  } as ModelRouting
  vault.writer()('modelRouting', old)
  vi.mocked(readModelRouting)
    .mockRejectedValueOnce(new Error('网络中断'))
    .mockResolvedValueOnce(current)
  render(
    <TestWorkspace vault={vault}>
      <Routing services={[]} initial={current} refresh={vi.fn()} />
    </TestWorkspace>,
  )
  expect(screen.queryByText('保存用途分配')).toBeNull()
  expect(vault.getSnapshot().modelRouting).toEqual(old)
  fireEvent.click(screen.getByRole('button', { name: '放弃旧草稿并读取当前配置' }))
  await screen.findByText('网络中断')
  expect(vault.getSnapshot().modelRouting).toEqual(old)
  fireEvent.click(screen.getByRole('button', { name: '放弃旧草稿并读取当前配置' }))
  await waitFor(() => expect(vault.getSnapshot().modelRouting).toEqual(current))
  expect(screen.getByText('保存用途分配')).toBeTruthy()
  expect(saveModelRouting).not.toHaveBeenCalled()
})
