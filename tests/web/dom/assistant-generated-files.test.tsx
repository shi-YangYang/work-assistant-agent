// @vitest-environment jsdom
import type { Deliverable, DeliverableFile, DeliverableSummary } from '@paa/api-contracts'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { setCsrf } from '../../../apps/web/src/api/client'
import { DeliverableEntry } from '../../../apps/web/src/features/assistant/components/deliverables/Deliverable'
import { GeneratedFiles } from '../../../apps/web/src/features/assistant/components/deliverables/GeneratedFiles'
import { deferred, dialogs } from './helpers'

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
  vi.mocked(fetch).mockResolvedValue(
    new Response(JSON.stringify({ error: { code: 'forbidden', message: '该文件无权查看' } }), {
      status: 403,
    }),
  )
  fireEvent.click(screen.getByRole('button', { name: `下载${image.name}` }))
  await screen.findByText('该文件无权查看')
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(clicked).toHaveLength(0)
  expect(screen.queryByRole('img')).toBeNull()
  expect(revokeUrl).toHaveBeenCalledWith('blob:generated')
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
