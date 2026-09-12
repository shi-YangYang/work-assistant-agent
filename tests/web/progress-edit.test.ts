import { expect, it } from 'vitest'
import type { Draft } from '../../src/shared/company-contracts'
import { progressEditValue } from '../../src/web/progress-edit'

it('submits explicit new-work null after normal editing and keeping edits through a conflict', () => {
  const draft: Draft = {
    id: 'draft',
    messageId: 'source',
    workId: 'old-work',
    revision: 1,
    status: 'pending',
    content: {
      title: '方案',
      summary: '初稿完成',
      status: 'in_progress',
      blocker: '',
      nextStep: '',
    },
  }
  const initial = progressEditValue(draft)
  expect(initial.workId).toBe('old-work')
  const selected = progressEditValue(draft, { ...initial, workId: null })
  expect(selected.workId).toBeNull()
  const kept = progressEditValue(draft, { ...selected, revision: 3 })
  expect({ ...kept.content, workId: kept.workId, expectedRevision: kept.revision }).toMatchObject({
    workId: null,
    expectedRevision: 3,
  })
})
