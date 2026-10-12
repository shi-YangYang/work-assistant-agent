// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { Work } from '@paa/api-contracts'
import { startTransition, StrictMode, Suspense, useState } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { patchWork } from '../../../../apps/web/src/features/work/api/requests'
import { WorkEditor } from '../../../../apps/web/src/features/work/components/editor/WorkEditor'
import { createVault, deferred, dialogs, identity, TestWorkspace } from '../helpers'

vi.mock('@web/features/work/api/requests', async (load) => ({
  ...(await load<typeof import('../../../../apps/web/src/features/work/api/requests')>()),
  patchWork: vi.fn(),
}))
const work = {
  id: 'work',
  title: '原工作',
  summary: '',
  status: 'in_progress',
  blocker: '',
  nextStep: '',
  dueDate: null,
  revision: 1,
} as Work
beforeEach(() => {
  dialogs()
  vi.clearAllMocks()
})
afterEach(cleanup)

it('locks submitted fields, rejects duplicate submit, and preserves edits after closing and reopening', async () => {
  const request = deferred<{ work: Work; materialIds: string[] }>(),
    saved = vi.fn(),
    vault = createVault()
  vi.mocked(patchWork).mockReturnValueOnce(request.promise)
  function Page() {
    const [open, setOpen] = useState(true)
    return (
      <TestWorkspace vault={vault}>
        {open ? (
          <WorkEditor work={work} onClose={() => setOpen(false)} onSaved={saved} />
        ) : (
          <button onClick={() => setOpen(true)}>重新打开</button>
        )}
      </TestWorkspace>
    )
  }
  render(<Page />)
  fireEvent.change(screen.getByRole('textbox', { name: '工作事项' }), {
    target: { value: '提交版本' },
  })
  fireEvent.click(screen.getByText('保存属性'))
  expect(screen.getByRole('textbox', { name: '工作事项' }).matches(':disabled')).toBe(true)
  expect(screen.getByRole('textbox', { name: '工作事项' }).matches(':disabled')).toBe(true)
  fireEvent.submit(screen.getByRole('textbox', { name: '工作事项' }).closest('form')!)
  expect(patchWork).toHaveBeenCalledTimes(1)
  fireEvent.click(screen.getByText('稍后继续'))
  fireEvent.click(screen.getByText('重新打开'))
  fireEvent.change(screen.getByRole('textbox', { name: '工作事项' }), {
    target: { value: '后来输入的版本' },
  })
  await act(async () => request.resolve({ work, materialIds: [] }))
  expect((screen.getByRole('textbox', { name: '工作事项' }) as HTMLInputElement).value).toBe(
    '后来输入的版本',
  )
  expect(saved).not.toHaveBeenCalled()
  expect(vault.getSnapshot()['work:metadata:work']).toMatchObject({
    content: { title: '后来输入的版本' },
  })
})

it('retains a failed draft and only clears its matching snapshot after a successful retry', async () => {
  const request = deferred<{ work: Work; materialIds: string[] }>(),
    saved = vi.fn(),
    vault = createVault()
  vi.mocked(patchWork)
    .mockReturnValueOnce(request.promise)
    .mockResolvedValueOnce({ work, materialIds: [] })
  render(
    <TestWorkspace vault={vault}>
      <WorkEditor work={work} onClose={vi.fn()} onSaved={saved} />
    </TestWorkspace>,
  )
  fireEvent.change(screen.getByRole('textbox', { name: '工作事项' }), {
    target: { value: '可恢复的草稿' },
  })
  fireEvent.click(screen.getByText('保存属性'))
  await act(async () => request.reject(new Error('网络已断开')))
  expect(screen.getByText('网络已断开')).toBeTruthy()
  expect(screen.getByRole('textbox', { name: '工作事项' }).matches(':disabled')).toBe(false)
  expect(vault.getSnapshot()['work:metadata:work']).toBeTruthy()
  fireEvent.click(screen.getByText('保存属性'))
  await waitFor(() => expect(saved).toHaveBeenCalledTimes(1))
  expect(vault.getSnapshot()['work:metadata:work']).toBeUndefined()
})

it.each(['record', 'account'] as const)(
  'ignores the previous response after changing %s while mounted',
  async (change) => {
    const request = deferred<{ work: Work; materialIds: string[] }>(),
      saved = vi.fn(),
      vault = createVault()
    vi.mocked(patchWork).mockReturnValueOnce(request.promise)
    const view = (nextWork = work, account = identity) => (
      <TestWorkspace vault={vault} account={account}>
        <WorkEditor work={nextWork} onClose={vi.fn()} onSaved={saved} />
      </TestWorkspace>
    )
    const mounted = render(view())
    fireEvent.change(screen.getByRole('textbox', { name: '工作事项' }), {
      target: { value: '旧请求' },
    })
    fireEvent.click(screen.getByText('保存属性'))
    const account =
      change === 'account' ? { ...identity, member: { ...identity.member, id: 'other' } } : identity
    const nextWork = change === 'record' ? { ...work, id: 'other', title: '另一条工作' } : work
    if (change === 'account') vault.resume(account)
    mounted.rerender(view(nextWork, account))
    fireEvent.change(screen.getByRole('textbox', { name: '工作事项' }), {
      target: { value: '新草稿' },
    })
    await act(async () => request.resolve({ work, materialIds: [] }))
    expect((screen.getByRole('textbox', { name: '工作事项' }) as HTMLInputElement).value).toBe(
      '新草稿',
    )
    expect(saved).not.toHaveBeenCalled()
  },
)

it('keeps the committed draft submission alive when navigation suspends in StrictMode', async () => {
  const request = deferred<{ work: Work; materialIds: string[] }>(),
    navigation = deferred<void>(),
    saved = vi.fn(),
    attemptedNavigation = vi.fn(),
    vault = createVault()
  vi.mocked(patchWork).mockReturnValueOnce(request.promise)
  function PendingNavigation({ pending }: { pending: boolean }) {
    if (pending) {
      attemptedNavigation()
      throw navigation.promise
    }
    return null
  }
  function Parent() {
    const [next, setNext] = useState(false)
    return (
      <TestWorkspace vault={vault}>
        <button onClick={() => startTransition(() => setNext(true))}>切换工作</button>
        <Suspense fallback={<p>加载工作</p>}>
          <WorkEditor
            work={next ? { ...work, id: 'next' } : work}
            onClose={vi.fn()}
            onSaved={saved}
          />
          <PendingNavigation pending={next} />
        </Suspense>
      </TestWorkspace>
    )
  }
  render(
    <StrictMode>
      <Parent />
    </StrictMode>,
  )
  fireEvent.change(screen.getByRole('textbox', { name: '工作事项' }), {
    target: { value: '提交当前工作' },
  })
  fireEvent.click(screen.getByText('保存属性'))
  fireEvent.click(screen.getByRole('button', { name: '切换工作' }))
  expect(attemptedNavigation).toHaveBeenCalled()
  expect(screen.queryByText('加载工作')).toBeNull()
  await act(async () => request.resolve({ work, materialIds: [] }))
  expect(saved).toHaveBeenCalledTimes(1)
  expect(vault.getSnapshot()['work:metadata:work']).toBeUndefined()
})

it('preserves a newer snapshot written to the same mounted draft during submission', async () => {
  const request = deferred<{ work: Work; materialIds: string[] }>(),
    saved = vi.fn(),
    vault = createVault()
  vi.mocked(patchWork).mockReturnValueOnce(request.promise)
  render(
    <TestWorkspace vault={vault}>
      <WorkEditor work={work} onClose={vi.fn()} onSaved={saved} />
    </TestWorkspace>,
  )
  fireEvent.change(screen.getByRole('textbox', { name: '工作事项' }), {
    target: { value: '提交版本' },
  })
  fireEvent.click(screen.getByText('保存属性'))
  const newer = { content: { ...work, title: '更新后的草稿' }, revision: work.revision }
  act(() => vault.writer()('work:metadata:work', newer))
  await act(async () => request.resolve({ work, materialIds: [] }))
  expect(saved).not.toHaveBeenCalled()
  expect(vault.getSnapshot()['work:metadata:work']).toBe(newer)
  expect((screen.getByRole('textbox', { name: '工作事项' }) as HTMLInputElement).value).toBe(
    '更新后的草稿',
  )
})
