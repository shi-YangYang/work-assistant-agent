// @vitest-environment jsdom
import type { Attachment } from '@paa/api-contracts'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import {
  deleteDraftAttachment,
  retryDocument,
  uploadAttachment,
} from '../../../../apps/web/src/api/attachments'
import { DocumentCard } from '../../../../apps/web/src/components/media/Documents'
import { Assistant } from '../../../../apps/web/src/features/assistant/components/conversation/Conversations'
import {
  readActiveAssistantJob,
  sendMessage,
} from '../../../../apps/web/src/features/assistant/api/requests'
import { createVault, deferred, dialogs, TestWorkspace } from '../helpers'
import { TestAttachmentUploads } from './attachment-upload-lifecycle'

vi.mock('@web/api/attachments', async (load) => ({
  ...(await load<typeof import('../../../../apps/web/src/api/attachments')>()),
  uploadAttachment: vi.fn(),
  deleteDraftAttachment: vi.fn(),
  retryDocument: vi.fn(),
}))
vi.mock('@web/features/assistant/api/requests', async (load) => ({
  ...(await load<typeof import('../../../../apps/web/src/features/assistant/api/requests')>()),
  readActiveAssistantJob: vi.fn(),
  sendMessage: vi.fn(),
}))

const tip = '旧版 Office 兼容提示'
const uploaded = (name: string): Attachment => ({
  id: name,
  name,
  kind: 'document',
  mime: 'application/octet-stream',
  size: 20,
  duration: null,
  url: `/api/v1/media/${name}`,
  extraction: { status: 'unsent', revision: 0, parserVersion: '' },
})
beforeEach(() => {
  dialogs()
  vi.clearAllMocks()
  vi.mocked(deleteDraftAttachment).mockResolvedValue({ ok: true })
  vi.mocked(readActiveAssistantJob).mockResolvedValue({ job: null })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const body = url.endsWith('/assistant/execution-settings')
        ? { executionMode: 'auto', modeRevision: 1, fullAccessConfirmed: false }
        : { items: [], nextCursor: null }
      return new Response(JSON.stringify(body), { status: 200 })
    }),
  )
  vi.stubGlobal(
    'EventSource',
    class extends EventTarget {
      close = vi.fn()
    },
  )
  URL.createObjectURL = vi.fn(() => 'blob:attachment')
  URL.revokeObjectURL = vi.fn()
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

it.each([1280, 390])(
  'keeps the Office advisory visible at %s px without bypassing upload/send rules',
  async (width) => {
    vi.stubGlobal('innerWidth', width)
    const first = deferred<Attachment>(),
      second = deferred<Attachment>(),
      third = deferred<Attachment>()
    vi.mocked(uploadAttachment)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)
      .mockReturnValueOnce(third.promise)
      .mockResolvedValueOnce(uploaded('新格式.docx'))
    vi.mocked(sendMessage).mockReturnValue(new Promise(() => {}))
    const view = render(
      <TestWorkspace vault={createVault()}>
        <TestAttachmentUploads />
        <MemoryRouter initialEntries={['/assistant?new=1']}>
          <Routes>
            <Route path="/assistant" element={<Assistant />} />
          </Routes>
        </MemoryRouter>
      </TestWorkspace>,
    )
    const select = (names: string[]) =>
      fireEvent.change(view.container.querySelector('input[type="file"]:not([accept])')!, {
        target: { files: names.map((name) => new File(['test material'], name)) },
      })
    select(['旧报告.DOC', '旧表格.xls'])
    await waitFor(() => expect(uploadAttachment).toHaveBeenCalledTimes(2))
    expect(screen.getAllByRole('note', { name: tip })).toHaveLength(1)
    expect(screen.getByRole('note', { name: tip }).textContent).toContain('Microsoft Office 或 WPS')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.queryByText('正在转换')).toBeNull()
    const send = screen.getByRole<HTMLButtonElement>('button', { name: '发送' })
    expect(send.disabled).toBe(true)
    fireEvent.click(send)
    fireEvent.keyDown(screen.getByRole('textbox', { name: '工作消息' }), { key: 'Enter' })
    expect(sendMessage).not.toHaveBeenCalled()

    select(['新格式.docx'])
    expect(screen.getAllByRole('note', { name: tip })).toHaveLength(1)
    await act(async () => {
      first.resolve(uploaded('旧报告.DOC'))
      second.resolve(uploaded('旧表格.xls'))
    })
    await waitFor(() => expect(uploadAttachment).toHaveBeenCalledTimes(3))
    expect(send.disabled).toBe(true)
    await act(async () => third.reject(new Error('offline')))
    expect(await screen.findByText('文件上传失败，请重试或移除。')).toBeTruthy()
    expect(screen.getByRole('note', { name: tip })).toBeTruthy()
    expect(send.disabled).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: '重试上传新格式.docx' }))
    await waitFor(() => expect(send.disabled).toBe(false))
    expect(uploadAttachment).toHaveBeenCalledTimes(4)
    expect(sendMessage).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: '移除旧报告.DOC' }))
    expect(screen.getByRole('note', { name: tip })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '移除旧表格.xls' }))
    expect(screen.queryByRole('note', { name: tip })).toBeNull()
    expect(screen.getByRole('article', { name: '新格式.docx' })).toBeTruthy()
    expect(deleteDraftAttachment).toHaveBeenCalledWith('旧报告.DOC')
    expect(deleteDraftAttachment).toHaveBeenCalledWith('旧表格.xls')
    fireEvent.click(send)
    await waitFor(() => expect(sendMessage).toHaveBeenCalledOnce())
    expect(vi.mocked(sendMessage).mock.calls[0][0].attachmentIds).toEqual(['新格式.docx'])
    expect(retryDocument).not.toHaveBeenCalled()
  },
)

it('uses processing stages without letting stale stages override terminal or historical statuses', () => {
  const attachment = uploaded('原件.doc'),
    refresh = vi.fn()
  const view = render(<DocumentCard attachment={attachment} own refresh={refresh} />)
  expect(screen.getByText(/上传完成，尚未发送/)).toBeTruthy()
  const states: [
    Omit<NonNullable<Attachment['extraction']>, 'revision' | 'parserVersion'>,
    string,
  ][] = [
    [{ status: 'pending' }, '等待解析'],
    [{ status: 'processing' }, '正在解析'],
    [{ status: 'processing', stage: 'queued' }, '等待转换'],
    [{ status: 'processing', stage: 'converting' }, '正在转换'],
    [{ status: 'processing', stage: 'parsing' }, '正在读取'],
    [{ status: 'ready', stage: 'converting' }, '文字可读'],
    [{ status: 'partial', stage: 'queued' }, '部分可读'],
    [{ status: 'failed', stage: 'parsing', error: '文件已加密，请解密后重新上传。' }, '解析失败'],
  ]
  for (const [extraction, label] of states) {
    view.rerender(
      <DocumentCard
        attachment={{
          ...attachment,
          extraction: { revision: 1, parserVersion: 'office-test', ...extraction },
        }}
        own
        refresh={refresh}
      />,
    )
    expect(screen.getByText(new RegExp(label))).toBeTruthy()
    expect(screen.queryByRole('button', { name: '查看提取内容' })).toBeNull()
    expect(screen.getByRole('link', { name: '下载原文件' }).getAttribute('href')).toBe(
      attachment.url,
    )
  }
  expect(screen.getByText('文件有密码，请解密后上传。')).toBeTruthy()
  expect(screen.queryByText(/正在读取/)).toBeNull()
  view.rerender(
    <DocumentCard
      attachment={{
        ...attachment,
        extraction: {
          status: 'partial',
          revision: 1,
          parserVersion: 'office-test',
          warnings: [
            '内容由 XLS 转换为 XLSX 后提取，复杂版式、图形及嵌入内容可能不完整。',
            '工作表「隐藏」已隐藏，未读取',
            '工作表「金额」隐藏的行／列未读取',
            '读取的是转换后的表格；公式保存结果已核对，未运行宏或刷新外部数据。',
          ],
        },
      }}
      own
      refresh={refresh}
    />,
  )
  expect(screen.getByText('图片和复杂排版可能不完整；隐藏的内容未读取。')).toBeTruthy()
  expect(screen.queryByText(/未运行宏或刷新外部数据/)).toBeNull()
})

it('keeps failed converted materials downloadable and retries only on an explicit action', async () => {
  const attachment: Attachment = {
    ...uploaded('原始预算.xls'),
    extraction: {
      status: 'failed',
      stage: 'converting',
      revision: 1,
      parserVersion: 'office-test',
      originalFormat: 'xls',
      convertedFormat: 'xlsx',
      error: '文件转换暂时不可用，请稍后重新解析。',
    },
  }
  const request = deferred<unknown>(),
    refresh = vi.fn()
  vi.mocked(retryDocument).mockReturnValue(request.promise)
  render(<DocumentCard attachment={attachment} own refresh={refresh} />)
  expect(screen.getByRole('link', { name: '下载原文件' }).getAttribute('download')).toBe(
    '原始预算.xls',
  )
  expect(retryDocument).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '重新解析' }))
  expect(retryDocument).toHaveBeenCalledExactlyOnceWith(attachment, {})
  await act(async () => request.resolve({ ok: true }))
  expect(refresh).toHaveBeenCalledOnce()
})
