// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { setCsrf } from '../../../../apps/web/src/api/client'
import { MemoryPage } from '../../../../apps/web/src/features/settings/components/memory/MemoryPage'
import { memoryResource } from '../../../../apps/web/src/features/settings/api/memory'
import { createVault, deferred, TestWorkspace } from '../helpers'

let saved = {
  enabled: true,
  revision: 0,
  markdown: '',
  updatedAt: null as string | null,
  maxCharacters: 6000,
}
let fail = false
function view() {
  return (
    <TestWorkspace vault={createVault()}>
      <MemoryRouter>
        <MemoryPage />
      </MemoryRouter>
    </TestWorkspace>
  )
}
beforeEach(() => {
  setCsrf('csrf', 'company:owner')
  saved = { enabled: true, revision: 0, markdown: '', updatedAt: null, maxCharacters: 6000 }
  fail = false
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, options: RequestInit) => {
      const method = options.method ?? 'GET'
      if (fail && method !== 'GET')
        return new Response(JSON.stringify({ error: { code: 'unavailable' } }), { status: 503 })
      const body = options.body ? JSON.parse(options.body as string) : {}
      if (method !== 'GET') {
        const revision = method === 'DELETE' ? Number(url.split('=')[1]) : body.expectedRevision
        if (revision !== saved.revision)
          return new Response(
            JSON.stringify({ error: { code: 'memory_conflict', message: '记忆已变化，请合并' } }),
            { status: 409 },
          )
        saved = {
          ...saved,
          ...(method === 'PATCH'
            ? { enabled: body.enabled }
            : { markdown: method === 'DELETE' ? '' : body.markdown }),
          revision: saved.revision + 1,
        }
      }
      return new Response(JSON.stringify(saved), { status: 200 })
    }),
  )
})
afterEach(() => {
  cleanup()
  setCsrf('')
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})
it('independently saves the accessible switch and edits/previews safely while disabled', async () => {
  render(view())
  const toggle = await screen.findByRole('switch', { name: '启用跨会话记忆' })
  fireEvent.click(toggle)
  await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('false'))
  fireEvent.click(screen.getByRole('button', { name: '编辑' }))
  fireEvent.change(screen.getByLabelText('记忆 Markdown'), {
    target: {
      value: '# 自定义\n\n<script>alert(1)</script>\n\n![外部](https://example.test/a.png)',
    },
  })
  fireEvent.click(screen.getByRole('button', { name: '预览' }))
  expect(document.querySelector('script')).toBeNull()
  expect(document.querySelector('img')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  await screen.findByRole('button', { name: '编辑' })
  expect(saved.markdown).toContain('# 自定义')
  expect(saved.enabled).toBe(false)
  vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
  fireEvent.click(screen.getByRole('button', { name: '清空记忆' }))
  expect(saved.markdown).not.toBe('')
  fireEvent.click(screen.getByRole('button', { name: '清空记忆' }))
  await screen.findByText(/还没有记忆/)
  expect(saved.enabled).toBe(false)
})
it('keeps a draft through concurrent updates and requires visible conflict resolution', async () => {
  render(view())
  await screen.findByRole('button', { name: '编辑' })
  fireEvent.click(screen.getByRole('button', { name: '编辑' }))
  fireEvent.change(screen.getByLabelText('记忆 Markdown'), { target: { value: '正在输入的草稿' } })
  saved = { ...saved, revision: 1, markdown: '其它页面新内容' }
  await act(async () => {
    memoryResource().set(saved)
  })
  expect((screen.getByLabelText('记忆 Markdown') as HTMLTextAreaElement).value).toBe(
    '正在输入的草稿',
  )
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  await screen.findByText(/已保留你的草稿/)
  fireEvent.click(screen.getByRole('button', { name: '读取最新版本' }))
  await screen.findByText('其它页面新内容')
  fireEvent.click(screen.getByRole('button', { name: '已核对，保留草稿继续编辑' }))
  fireEvent.change(screen.getByLabelText('记忆 Markdown'), {
    target: { value: '其它页面新内容\n\n正在输入的草稿' },
  })
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  await screen.findByRole('button', { name: '编辑' })
  expect(saved.markdown).toContain('其它页面新内容')
  expect(saved.markdown).toContain('正在输入的草稿')
})
it('keeps the switch unchanged on failure, cancels drafts and rejects over-capacity text', async () => {
  render(view())
  const toggle = await screen.findByRole('switch')
  fail = true
  fireEvent.click(toggle)
  await screen.findByRole('alert')
  expect(toggle.getAttribute('aria-checked')).toBe('true')
  fireEvent.click(screen.getByRole('button', { name: '编辑' }))
  fireEvent.change(screen.getByLabelText('记忆 Markdown'), { target: { value: 'x'.repeat(6001) } })
  expect((screen.getByRole('button', { name: '保存' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '取消' }))
  expect(saved.markdown).toBe('')
})
it('prevents duplicate switch submission until the server acknowledges it', async () => {
  render(view())
  const toggle = await screen.findByRole('switch')
  const pending = deferred<Response>()
  vi.mocked(fetch).mockImplementationOnce(() => pending.promise)
  fireEvent.click(toggle)
  fireEvent.click(toggle)
  expect((toggle as HTMLButtonElement).disabled).toBe(true)
  expect(toggle.getAttribute('aria-checked')).toBe('true')
  await act(async () => {
    pending.resolve(new Response(JSON.stringify({ ...saved, enabled: false, revision: 1 })))
  })
  expect(toggle.getAttribute('aria-checked')).toBe('false')
})

it('formats selected Markdown without losing surrounding text, previews and saves the source', async () => {
  render(view())
  fireEvent.click(await screen.findByRole('button', { name: '编辑' }))
  const input = screen.getByLabelText('记忆 Markdown') as HTMLTextAreaElement
  fireEvent.change(input, { target: { value: '我喜欢简洁回答。\n保留这一行。' } })
  input.setSelectionRange(3, 7)
  fireEvent.click(screen.getByRole('button', { name: '加粗' }))
  expect(input.value).toBe('我喜欢**简洁回答**。\n保留这一行。')
  expect(input.value.slice(input.selectionStart, input.selectionEnd)).toBe('简洁回答')
  expect(document.activeElement).toBe(input)
  fireEvent.click(screen.getByRole('button', { name: '预览' }))
  const preview = screen.getByRole('region', { name: '记忆 Markdown预览' })
  expect(preview.querySelector('strong')?.textContent).toBe('简洁回答')
  fireEvent.click(screen.getByRole('button', { name: '继续编辑' }))
  expect(input.value).toBe('我喜欢**简洁回答**。\n保留这一行。')
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  await screen.findByRole('button', { name: '编辑' })
  expect(saved.markdown).toBe('我喜欢**简洁回答**。\n保留这一行。')
})

it('formats complete selected lines and keyboard selections, then discards unsaved changes', async () => {
  render(view())
  fireEvent.click(await screen.findByRole('button', { name: '编辑' }))
  const input = screen.getByLabelText('记忆 Markdown') as HTMLTextAreaElement
  fireEvent.change(input, { target: { value: '偏好\n先结论\n再细节\n末尾' } })
  input.setSelectionRange(3, 11)
  fireEvent.click(screen.getByRole('button', { name: '有序列表' }))
  expect(input.value).toBe('偏好\n1. 先结论\n2. 再细节\n末尾')
  input.setSelectionRange(0, 2)
  fireEvent.keyDown(input, { key: 'i', ctrlKey: true })
  expect(input.value).toBe('*偏好*\n1. 先结论\n2. 再细节\n末尾')
  fireEvent.keyDown(input, { key: 'i', ctrlKey: true })
  expect(input.value).toBe('偏好\n1. 先结论\n2. 再细节\n末尾')
  fireEvent.click(screen.getByRole('button', { name: '取消' }))
  fireEvent.click(screen.getByRole('button', { name: '编辑' }))
  expect((screen.getByLabelText('记忆 Markdown') as HTMLTextAreaElement).value).toBe('')
  expect(saved.markdown).toBe('')
})

it('inserts headings, links and code with editable placeholders and locks formatting during save', async () => {
  render(view())
  fireEvent.click(await screen.findByRole('button', { name: '编辑' }))
  const input = screen.getByLabelText('记忆 Markdown') as HTMLTextAreaElement
  fireEvent.click(screen.getByRole('button', { name: '小标题' }))
  expect(input.value).toBe('## 标题')
  fireEvent.change(input, { target: { value: '主页' } })
  input.setSelectionRange(0, 2)
  fireEvent.click(screen.getByRole('button', { name: '链接' }))
  expect(input.value).toBe('[主页](https://)')
  expect(input.value.slice(input.selectionStart, input.selectionEnd)).toBe('https://')
  fireEvent.change(input, { target: { value: 'print(1)' } })
  input.setSelectionRange(0, 8)
  fireEvent.click(screen.getByRole('button', { name: '代码块' }))
  expect(input.value).toBe('```\nprint(1)\n```')
  const pending = deferred<Response>()
  vi.mocked(fetch).mockImplementationOnce(() => pending.promise)
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  expect(input.disabled).toBe(true)
  expect((screen.getByRole('button', { name: '加粗' }) as HTMLButtonElement).disabled).toBe(true)
  await act(async () => {
    pending.resolve(new Response(JSON.stringify({ ...saved, markdown: input.value, revision: 1 })))
  })
  await screen.findByRole('button', { name: '编辑' })
})
