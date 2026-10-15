import { expect, it } from 'vitest'
import { numberedFiles } from '../../../apps/web/src/features/assistant/lib/attachment-names'

it('keeps identical files uploadable with stable numbered names across selection batches', async () => {
  const file = new File(['same content'], '发票.pdf', {
    type: 'application/pdf',
    lastModified: 123,
  })
  const first = numberedFiles([file, file], [])
  const second = numberedFiles([file], first)
  expect([...first, ...second].map((entry) => entry.name)).toEqual([
    '发票.pdf',
    '发票 (2).pdf',
    '发票 (3).pdf',
  ])
  expect(first[0]).toBe(file)
  expect(await second[0].text()).toBe(await file.text())
  expect(second[0].type).toBe(file.type)
  expect(second[0].lastModified).toBe(file.lastModified)
  expect(numberedFiles([file], [first[0]])[0].name).toBe('发票 (2).pdf')
  expect(numberedFiles([file], [])[0]).toBe(file)
})

it('preserves distinct bytes and avoids collisions with already numbered and long Unicode names', async () => {
  const files = [
    new File(['a'], '方案.txt'),
    new File(['b'], '方案.txt'),
    new File(['c'], '方案 (2).txt'),
  ]
  const result = numberedFiles(files, [])
  expect(result.map((file) => file.name)).toEqual(['方案.txt', '方案 (3).txt', '方案 (2).txt'])
  expect(await Promise.all(result.map((file) => file.text()))).toEqual(['a', 'b', 'c'])
  for (const name of ['长'.repeat(190) + '.txt', '🙂'.repeat(190) + '.txt', '.env', 'README']) {
    const file = new File(['data'], name)
    const renamed = numberedFiles([file, file, file], [])
    expect(new Set(renamed.map((entry) => entry.name)).size).toBe(3)
    expect(renamed.every((entry) => Array.from(entry.name).length <= 180)).toBe(true)
  }
})
