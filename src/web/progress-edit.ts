import type { Draft, Progress } from '../shared/company-contracts'

export type ProgressEdit = { content: Progress; workId: string | null; revision: number }

export function progressEditValue(draft: Draft, stored?: ProgressEdit): ProgressEdit {
  // An explicit null means the employee chose a new work item, not no edit.
  return stored ?? { content: draft.content, workId: draft.workId, revision: draft.revision }
}
