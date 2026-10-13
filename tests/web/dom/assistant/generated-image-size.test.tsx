// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { GeneratedFiles } from '../../../../apps/web/src/features/assistant/components/deliverables/GeneratedFiles'

vi.mock('../../../../apps/web/src/features/assistant/hooks/deliverables/useGeneratedFile', () => ({
  useGeneratedFile: () => ({ download: vi.fn(), busy: false, error: '' }),
  useGeneratedImage: () => ({ url: 'blob:private-png', error: '', retry: vi.fn() }),
}))
afterEach(cleanup)
it('shows decoded dimensions for new PNGs and keeps old generated files readable', () => {
  render(
    <GeneratedFiles
      deliverableId="image"
      revision={1}
      files={[
        {
          id: 'new',
          name: 'image.png',
          mimeType: 'image/png',
          size: 1000,
          url: '/private',
          width: 1000,
          height: 800,
        },
        { id: 'old', name: 'chart.png', mimeType: 'image/png', size: 500, url: '/private-old' },
      ]}
    />,
  )
  expect(screen.getByText(/1000 × 800/)).toBeTruthy()
  expect(screen.getByRole('img', { name: 'image.png' })).toBeTruthy()
  expect(screen.getByRole('button', { name: '下载chart.png' })).toBeTruthy()
})
