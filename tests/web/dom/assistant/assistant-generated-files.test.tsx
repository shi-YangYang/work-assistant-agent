// @vitest-environment jsdom
import type { Deliverable, DeliverableFile, DeliverableSummary } from '@paa/api-contracts'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { setCsrf } from '../../../../apps/web/src/api/client'
import {
  DeliverableEntry,
  MessageDeliverables,
} from '../../../../apps/web/src/features/assistant/components/deliverables/Deliverable'
import { GeneratedFiles } from '../../../../apps/web/src/features/assistant/components/deliverables/GeneratedFiles'
import { deferred, dialogs } from '../helpers'

const summary: DeliverableSummary = {
  id: 'result',
  revision: 2,
  latestRevision: 2,
  title: '销售分析',
  messageId: 'message',
  itemCount: 0,
  updatedAt: '2026-09-29T10:00:00Z',
}
function file(
  name = '分析.pptx',
  mimeType = 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  revision = 2,
): DeliverableFile {
  return {
    id: name,
    name,
    mimeType,
    size: 4,
    url: `/api/v1/deliverables/result/files/${encodeURIComponent(name)}?revision=${revision}`,
  }
}
const createUrl = vi.fn(() => 'blob:generated')
const revokeUrl = vi.fn()
const clicked: { url: string; name: string }[] = []
beforeEach(() => {
  // Canvas rendering is checked in the browser; jsdom only exercises slot state.
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
  setCsrf('csrf', 'company:owner')
  dialogs()
  createUrl.mockClear()
  revokeUrl.mockClear()
  clicked.length = 0
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(new Uint8Array([1, 2, 3, 4]))),
  )
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    clicked.push({ url: this.href, name: this.download })
  })
  URL.createObjectURL = createUrl
  URL.revokeObjectURL = revokeUrl
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('leaves existing text-only deliverables unchanged and does not fetch generated files', () => {
  render(<DeliverableEntry item={summary} />)
  expect(screen.queryByRole('list')).toBeNull()
  expect(screen.getByRole('button', { name: '查看销售分析' })).toBeTruthy()
  expect(fetch).not.toHaveBeenCalled()
})

it('keeps incremental images in one strip and adds one task entry after the reply completes', async () => {
  const items = [1, 2, 3, 4].map((number) => ({
    ...summary,
    id: `image-${number}`,
    title: '3D猫和老鼠（4张）',
    files: [
      {
        ...file('image.png', 'image/png'),
        url: `/api/v1/deliverables/image-${number}/files/image.png?revision=2`,
      },
    ],
  }))
  const view = render(<MessageDeliverables items={items.slice(0, 1)} complete={false} />)
  const strip = screen.getByRole('list', { name: '生成图片' })
  await within(strip).findByRole('button', { name: '预览image.png' })
  expect(screen.queryByRole('button', { name: /^查看/ })).toBeNull()
  view.rerender(<MessageDeliverables items={items} complete={false} />)
  await waitFor(() =>
    expect(within(strip).getAllByRole('button', { name: '预览image.png' })).toHaveLength(4),
  )
  expect(within(strip).getAllByRole('listitem')).toHaveLength(4)
  expect(screen.getAllByRole('list')).toHaveLength(1)
  expect(screen.queryByRole('button', { name: /^查看/ })).toBeNull()
  // Completing the reply must neither remount nor fetch the thumbnails again.
  view.rerender(<MessageDeliverables items={items} complete />)
  expect(screen.getAllByRole('button', { name: /^查看/ })).toHaveLength(1)
  expect(fetch).toHaveBeenCalledTimes(4)
  expect(screen.getByRole('list', { name: '生成图片' })).toBe(strip)
  expect(strip.querySelector('button')?.textContent).not.toContain('查看')
  fireEvent.click(within(strip).getAllByRole('button', { name: '预览image.png' })[2])
  expect(screen.getByRole('dialog', { name: 'image.png' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '关闭' }))
  expect(screen.queryByRole('dialog')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '查看3D猫和老鼠（4张）' }))
  const task = screen.getByRole('dialog', { name: '3D猫和老鼠（4张）' })
  await waitFor(() =>
    expect(within(task).getAllByRole('button', { name: '预览image.png' })).toHaveLength(4),
  )
  fireEvent.click(within(task).getAllByRole('button', { name: '预览image.png' })[3])
  const preview = screen.getByRole('dialog', { name: 'image.png' })
  fireEvent.click(within(preview).getByRole('button', { name: '下载原图片' }))
  await waitFor(() => expect(clicked).toHaveLength(1))
  expect(fetch).toHaveBeenLastCalledWith(items[3].files[0].url, expect.anything())
  fireEvent.click(within(preview).getByRole('button', { name: '关闭' }))
  fireEvent.click(within(task).getByRole('button', { name: '关闭' }))
  expect(screen.queryByRole('dialog')).toBeNull()
})

it('shows all supported file formats and downloads only the selected file through the authenticated client', async () => {
  const formats = [
    ['说明.txt', 'text/plain'],
    ['说明.md', 'text/markdown'],
    ['数据.json', 'application/json'],
    ['数据.csv', 'text/csv'],
    ['数据.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'],
    ['报告.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
    ['报告.pdf', 'application/pdf'],
    [
      '一个很长的中文演示文稿文件名需要在窄屏正常显示而不把下载按钮挤出去.pptx',
      'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    ],
  ]
  const files = formats.map(([name, mime]) => file(name, mime))
  const view = render(<GeneratedFiles deliverableId="result" revision={2} files={files} />)
  expect(screen.getAllByRole('listitem')).toHaveLength(8)
  expect(fetch).not.toHaveBeenCalled()
  const chosen = files.at(-1)!
  fireEvent.click(screen.getByRole('button', { name: `下载${chosen.name}` }))
  await waitFor(() => expect(clicked).toEqual([{ url: 'blob:generated', name: chosen.name }]))
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(fetch).toHaveBeenCalledWith(
    chosen.url,
    expect.objectContaining({ credentials: 'same-origin', cache: 'no-store' }),
  )
  view.unmount()
  expect(revokeUrl).toHaveBeenCalledWith('blob:generated')
})

it('coalesces repeated clicks during a download without submitting any business write', async () => {
  const response = deferred<Response>()
  vi.mocked(fetch).mockReturnValue(response.promise)
  render(<GeneratedFiles deliverableId="result" revision={2} files={[file()]} />)
  const button = screen.getByRole('button', { name: '下载分析.pptx' })
  fireEvent.click(button)
  fireEvent.click(button)
  expect(fetch).toHaveBeenCalledOnce()
  expect(screen.getByRole('button', { name: '正在下载分析.pptx' }).hasAttribute('disabled')).toBe(
    true,
  )
  response.resolve(new Response(new Uint8Array([1, 2, 3, 4])))
  await waitFor(() => expect(clicked).toHaveLength(1))
  expect(vi.mocked(fetch).mock.calls[0][1]?.method).toBeUndefined()
})

it('previews PNGs inline, handles image decode errors, and revokes preview URLs when removed', async () => {
  const image = file('销售趋势.png', 'image/png')
  const view = render(<GeneratedFiles deliverableId="result" revision={2} files={[image]} />)
  expect(screen.getByRole('status').textContent).toBe('正在读取图片…')
  const preview = await screen.findByRole('img', { name: image.name })
  expect(preview.getAttribute('src')).toBe('blob:generated')
  fireEvent.error(preview)
  expect(screen.getByText('图片无法预览，可下载文件查看。')).toBeTruthy()
  expect(screen.getByRole('button', { name: `下载${image.name}` })).toBeTruthy()
  view.unmount()
  expect(revokeUrl).toHaveBeenCalledWith('blob:generated')
})

it('rechecks download authorization and removes a previously loaded preview after access is denied', async () => {
  const image = file('销售趋势.png', 'image/png')
  render(<GeneratedFiles deliverableId="result" revision={2} files={[image]} />)
  await screen.findByRole('img', { name: image.name })
  fireEvent.click(screen.getByRole('button', { name: `预览${image.name}` }))
  vi.mocked(fetch).mockResolvedValue(
    new Response(JSON.stringify({ error: { code: 'forbidden', message: '该文件无权查看' } }), {
      status: 403,
    }),
  )
  fireEvent.click(screen.getByRole('button', { name: '下载原图片' }))
  await screen.findByText('该文件无权查看')
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(clicked).toHaveLength(0)
  expect(screen.queryByRole('img')).toBeNull()
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(revokeUrl).toHaveBeenCalledWith('blob:generated')
})

it('opens a compact image in the gallery and keeps download errors and retry inside the preview', async () => {
  const image = file('猫和老鼠.png', 'image/png')
  render(<GeneratedFiles deliverableId="result" revision={2} files={[image]} />)
  const thumbnail = await screen.findByRole('button', { name: `预览${image.name}` })
  expect(screen.queryByText(image.name)).toBeNull()
  expect(screen.queryByText(/PNG ·/)).toBeNull()
  expect(screen.queryByRole('button', { name: `下载${image.name}` })).toBeNull()
  thumbnail.focus()
  fireEvent.click(thumbnail)
  const dialog = screen.getByRole('dialog', { name: image.name })
  expect(within(dialog).getByRole('img', { name: image.name }).getAttribute('src')).toBe(
    'blob:generated',
  )
  expect(fetch).toHaveBeenCalledTimes(1)
  fireEvent.click(within(dialog).getByRole('button', { name: '放大图片' }))
  expect(within(dialog).getByText('125%')).toBeTruthy()
  vi.mocked(fetch).mockRejectedValueOnce(new TypeError('offline'))
  fireEvent.click(within(dialog).getByRole('button', { name: '下载原图片' }))
  await within(dialog).findByText('无法连接服务，请检查网络后重试。')
  fireEvent.click(within(dialog).getByRole('button', { name: '重试' }))
  await waitFor(() => expect(clicked).toEqual([{ url: 'blob:generated', name: image.name }]))
  expect(fetch).toHaveBeenCalledTimes(3)
  fireEvent.click(within(dialog).getByRole('button', { name: '关闭' }))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(document.activeElement).toBe(thumbnail)
})

it('offers an explicit retry after a transient failure without polling', async () => {
  vi.mocked(fetch).mockRejectedValueOnce(new TypeError('offline'))
  render(<GeneratedFiles deliverableId="result" revision={2} files={[file()]} />)
  fireEvent.click(screen.getByRole('button', { name: '下载分析.pptx' }))
  await screen.findByText('无法连接服务，请检查网络后重试。')
  expect(fetch).toHaveBeenCalledOnce()
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  await waitFor(() => expect(clicked).toHaveLength(1))
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(screen.queryByRole('alert')).toBeNull()
})

it('discards a late download response when the signed-in account changes', async () => {
  const response = deferred<Response>()
  vi.mocked(fetch).mockReturnValue(response.promise)
  render(<GeneratedFiles deliverableId="result" revision={2} files={[file()]} />)
  fireEvent.click(screen.getByRole('button', { name: '下载分析.pptx' }))
  setCsrf('other-csrf', 'other-company:other-owner')
  await act(async () => {
    response.resolve(new Response(new Uint8Array([1, 2, 3, 4])))
    await response.promise
  })
  expect(vi.mocked(fetch).mock.calls[0][1]?.signal?.aborted).toBe(true)
  expect(clicked).toHaveLength(0)
  expect(createUrl).not.toHaveBeenCalled()
})

it('aborts pending preview reads on removal and never installs their late result', async () => {
  const response = deferred<Response>()
  vi.mocked(fetch).mockReturnValue(response.promise)
  const view = render(
    <GeneratedFiles deliverableId="result" revision={2} files={[file('图.png', 'image/png')]} />,
  )
  view.unmount()
  expect(vi.mocked(fetch).mock.calls[0][1]?.signal?.aborted).toBe(true)
  await act(async () => {
    response.resolve(new Response(new Uint8Array([1, 2, 3, 4])))
    await response.promise
  })
  expect(createUrl).not.toHaveBeenCalled()
})

it.each([
  'https://example.com/steal',
  '/api/v1/deliverables/other/files/private?revision=2',
  'javascript:alert(1)',
])('rejects file URLs outside the exact deliverable revision: %s', async (url) => {
  render(<GeneratedFiles deliverableId="result" revision={2} files={[{ ...file(), url }]} />)
  fireEvent.click(screen.getByRole('button', { name: '下载分析.pptx' }))
  await screen.findByText('文件地址无效，请重新打开成果。')
  expect(fetch).not.toHaveBeenCalled()
  expect(clicked).toHaveLength(0)
})

it('does not download a truncated response as a successful file', async () => {
  vi.mocked(fetch).mockResolvedValue(new Response(new Uint8Array([1])))
  render(<GeneratedFiles deliverableId="result" revision={2} files={[file()]} />)
  fireEvent.click(screen.getByRole('button', { name: '下载分析.pptx' }))
  await screen.findByText('文件未完整读取，请重试。')
  expect(clicked).toHaveLength(0)
})

it('keeps the requested version for file downloads and subsequent chat edits', async () => {
  vi.mocked(fetch).mockImplementation(async (url) => {
    const revision = String(url).includes('revision=1') ? 1 : 2
    if (String(url).includes('/files/')) return new Response(new Uint8Array([1, 2, 3, 4]))
    const result: Deliverable = {
      ...summary,
      revision,
      body: '分析结果',
      items: [],
      links: [],
      files: [file(`分析-${revision}.pptx`, file().mimeType, revision)],
    }
    return new Response(JSON.stringify(result))
  })
  const onContinue = vi.fn()
  render(
    <DeliverableEntry
      item={{ ...summary, files: [file('分析-2.pptx')] }}
      onContinue={onContinue}
    />,
  )
  fireEvent.click(screen.getByRole('button', { name: '查看销售分析' }))
  const dialog = await screen.findByRole('dialog')
  await within(dialog).findByText('分析结果')
  fireEvent.click(within(dialog).getByText('版本 2'))
  fireEvent.click(within(dialog).getByRole('button', { name: '上一版本' }))
  fireEvent.click(await within(dialog).findByRole('button', { name: '下载分析-1.pptx' }))
  await waitFor(() => expect(clicked).toHaveLength(1))
  expect(fetch).toHaveBeenLastCalledWith(
    file('分析-1.pptx', file().mimeType, 1).url,
    expect.objectContaining({ cache: 'no-store' }),
  )
  fireEvent.click(within(dialog).getByRole('button', { name: '继续修改' }))
  expect(onContinue).toHaveBeenCalledWith(
    { id: 'result', revision: 1, itemIds: [] },
    summary.title,
    undefined,
  )
})

it('reserves every image slot before delivery, replaces in place and stops terminal placeholders', async () => {
  const generation: import('@paa/api-contracts').ImageGenerationSlot[] = [
    { operation: 1, state: 'generating', width: 2048, height: 2048 },
    { operation: 2, state: 'queued' },
    { operation: 3, state: 'queued' },
    { operation: 4, state: 'queued' },
  ]
  const view = render(
    <MessageDeliverables items={[]} generation={generation} state="running" complete={false} />,
  )
  const strip = screen.getByRole('list', { name: '生成图片' })
  expect(within(strip).getAllByRole('listitem')).toHaveLength(4)
  expect(screen.getByRole('status', { name: '第 1 张图片：正在生成' })).toBeTruthy()
  expect(screen.getByRole('status', { name: '第 4 张图片：等待生成' })).toBeTruthy()
  expect(fetch).not.toHaveBeenCalled()
  const item = { ...summary, files: [file('cat.png', 'image/png')] }
  const updated = generation.map((slot) =>
    slot.operation === 1
      ? { ...slot, state: 'ready' as const, deliverableId: item.id, revision: item.revision }
      : slot.operation === 2
        ? { ...slot, state: 'failed' as const }
        : slot.operation === 3
          ? { ...slot, state: 'generating' as const }
          : slot,
  )
  view.rerender(
    <MessageDeliverables items={[item]} generation={updated} state="running" complete={false} />,
  )
  await within(strip).findByRole('button', { name: '预览cat.png' })
  expect(within(strip).getAllByRole('listitem')).toHaveLength(4)
  expect(within(strip).getAllByRole('listitem')[0].querySelector('img')).toBeTruthy()
  expect(screen.getByRole('status', { name: '第 2 张图片：生成失败' }).dataset.active).toBe('false')
  expect(screen.getByRole('status', { name: '第 3 张图片：正在生成' }).dataset.active).toBe('true')
  expect(screen.queryByRole('button', { name: /^查看/ })).toBeNull()
  view.rerender(
    <MessageDeliverables items={[item]} generation={updated} state="cancelled" complete />,
  )
  for (const operation of [3, 4]) {
    const cancelled = screen.getByRole('status', { name: `第 ${operation} 张图片：已取消` })
    expect(cancelled.dataset.active).toBe('false')
    expect(cancelled.querySelector('canvas')).toBeNull()
  }
  expect(within(strip).getAllByRole('listitem')).toHaveLength(4)
  expect(fetch).toHaveBeenCalledTimes(1)

  // Reloading a completed result is a file read, never a new generation.
  view.unmount()
  const response = deferred<Response>()
  vi.mocked(fetch).mockReturnValueOnce(response.promise)
  render(
    <MessageDeliverables items={[item]} generation={[updated[0]]} state="succeeded" complete />,
  )
  const loading = screen.getByRole('status', { name: '第 1 张图片：加载图片…' })
  expect(loading.dataset.active).toBe('false')
  expect(loading.querySelector('canvas')).toBeNull()
  response.resolve(new Response(new Uint8Array([1, 2, 3, 4])))
  await screen.findByRole('button', { name: '预览cat.png' })
  expect(screen.queryByRole('status')).toBeNull()
})
