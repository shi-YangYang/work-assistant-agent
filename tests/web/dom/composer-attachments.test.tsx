// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ComposerAttachments } from '../../../apps/web/src/features/assistant/components/composer/ComposerAttachments'
import type { Composer } from '../../../apps/web/src/features/assistant/lib/audio-capture'
import { recordingPreview } from '../../../apps/web/src/features/assistant/lib/audio-preview'

vi.mock('@web/features/assistant/lib/audio-preview', () => ({ recordingPreview: vi.fn() }))

const item = (id: string, name: string, recorded = false) => ({
  id,
  file: new File(['contents'], name),
  url: `blob:${id}`,
  recorded,
})
function setup(files: Composer['files'], extra: Partial<Composer> = {}, locked = false) {
  const composer = { text: '整理这些材料', key: 'draft', files, ...extra }
  const change = vi.fn(),
    setGallery = vi.fn(),
    setPdf = vi.fn()
  const props = {
    composer,
    change,
    setGallery,
    setPdf,
    locked,
    previewImages: files
      .filter(({ file }) => file.name.endsWith('.png'))
      .map((file) => ({
        id: file.id,
        name: file.file.name,
        src: file.url,
        original: file.url,
      })),
  }
  return { ...render(<ComposerAttachments {...props} />), props, change, setGallery, setPdf }
}
beforeEach(() => {
  vi.stubGlobal(
    'URL',
    Object.assign(URL, {
      createObjectURL: vi.fn(() => 'blob:converted'),
      revokeObjectURL: vi.fn(),
    }),
  )
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(function (
    this: HTMLMediaElement,
  ) {
    Object.defineProperty(this, 'paused', { configurable: true, value: false })
    this.dispatchEvent(new Event('play'))
    return Promise.resolve()
  })
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(function (
    this: HTMLMediaElement,
  ) {
    Object.defineProperty(this, 'paused', { configurable: true, value: true })
    this.dispatchEvent(new Event('pause'))
  })
  vi.mocked(recordingPreview).mockReset()
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('keeps all nine mixed attachments in selection order and preserves preview, removal and draft data', () => {
  const files = [
    item('image', '方案.png'),
    item('audio', '采访.wav'),
    item('pdf', '需求.pdf'),
    ...Array.from({ length: 6 }, (_, i) => item(`image${i}`, `现场${i}.png`)),
  ]
  const view = setup(files, { replyTo: 'earlier-message' })
  expect(screen.getAllByRole('article').map((node) => node.getAttribute('aria-label'))).toEqual(
    files.map((entry) => entry.file.name),
  )
  fireEvent.click(screen.getByRole('button', { name: '预览现场2.png' }))
  expect(view.setGallery).toHaveBeenCalledWith(3)
  fireEvent.click(screen.getByRole('button', { name: '预览需求.pdf' }))
  expect(view.setPdf).toHaveBeenCalledWith(files[2].file)
  fireEvent.click(screen.getByRole('button', { name: '移除采访.wav' }))
  expect(view.change).toHaveBeenCalledWith({
    ...view.props.composer,
    key: '',
    files: files.filter((f) => f.id !== 'audio'),
  })
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:audio')
  expect(screen.queryByText('待上传')).toBeNull()
})

it('loads duration without displaying a fake zero and pauses the previous audio when switching or removing', async () => {
  const view = setup([item('one', '第一段.wav'), item('two', '第二段.wav')])
  const [first, second] = view.container.querySelectorAll('audio')
  expect(screen.queryByText('0:00')).toBeNull()
  Object.defineProperty(first, 'duration', { value: 64 })
  fireEvent.loadedMetadata(first)
  expect(screen.getByText('1:04')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '播放第一段.wav' }))
  expect(screen.getByRole('button', { name: '暂停第一段.wav' })).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '播放第二段.wav' }))
  expect(first.paused).toBe(true)
  expect(second.paused).toBe(false)
  expect(screen.getByRole('button', { name: '播放第一段.wav' })).toBeTruthy()
  view.rerender(
    <ComposerAttachments
      {...view.props}
      composer={{ ...view.props.composer, files: [view.props.composer.files[0]] }}
    />,
  )
  expect(second.paused).toBe(true)
  await act(async () => {})
})

it('keeps decoded recording duration and uses the same player for compact and expanded controls', async () => {
  const wav = new Blob(['wav'], { type: 'audio/wav' })
  vi.mocked(recordingPreview).mockResolvedValue(wav)
  const files = [item('recording', '语音.webm', true)]
  const view = setup(files)
  expect(screen.getByRole<HTMLButtonElement>('button', { name: '播放语音 1' }).disabled).toBe(true)
  await waitFor(() =>
    expect(view.container.querySelector('audio')?.getAttribute('src')).toBe('blob:converted'),
  )
  expect(recordingPreview).toHaveBeenCalledWith(files[0].file)
  expect(view.container.querySelectorAll('audio')).toHaveLength(1)
  const trigger = screen.getByRole('button', { name: '展开语音 1试听' })
  expect(
    document.getElementById(trigger.getAttribute('popovertarget')!)?.querySelector('audio'),
  ).toBeTruthy()
  view.unmount()
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:converted')
})

it('keeps failed recordings sendable and upload errors visible, with removals locked during send', async () => {
  vi.mocked(recordingPreview).mockRejectedValue(new Error('decode error'))
  const files = [item('voice', '语音.webm', true), { ...item('image', '图片.png'), failed: true }]
  const view = setup(files, {}, true)
  await screen.findByText('无法试听')
  expect(screen.getByText('上传失败')).toBeTruthy()
  expect(screen.getByRole<HTMLButtonElement>('button', { name: '移除图片.png' }).disabled).toBe(
    true,
  )
  expect(view.change).not.toHaveBeenCalled()
})

it('does not allocate a preview URL when conversion completes after removal', async () => {
  let resolve!: (value: Blob) => void
  vi.mocked(recordingPreview).mockReturnValue(
    new Promise((done) => {
      resolve = done
    }),
  )
  const view = setup([item('voice', '语音.webm', true)])
  view.unmount()
  await act(async () => resolve(new Blob(['wav'])))
  expect(URL.createObjectURL).not.toHaveBeenCalled()
})
