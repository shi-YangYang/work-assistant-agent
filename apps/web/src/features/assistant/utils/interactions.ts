import type { AssistantInteraction } from '@paa/api-contracts'

// Later sources are more authoritative: local response, message/SSE, then a fresh query.
// Revoked-source projections may keep the same stored revision; never restore their text
// from an optimistic response or an older feedback snapshot.
export function mergeInteractions(...snapshots: (AssistantInteraction[] | undefined)[]) {
  const merged = new Map<string, AssistantInteraction>()
  for (const snapshot of snapshots)
    for (const item of snapshot ?? []) {
      const previous = merged.get(item.id)
      if (item.state === 'expired') {
        merged.set(item.id, { ...item, questions: [], answers: [] })
      } else if (
        !previous ||
        item.revision > previous.revision ||
        (item.revision === previous.revision &&
          previous.state !== 'expired' &&
          item.state !== 'waiting')
      ) {
        merged.set(item.id, item)
      }
    }
  return [...merged.values()].sort((a, b) => a.createdAt.localeCompare(b.createdAt))
}
