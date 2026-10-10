import type { AssistantMemory } from '@paa/api-contracts'
import { api, queryIdentity, write } from '@web/api/client'
import { QueryResource, sharedResource } from '@web/lib/query-resource'

export const memoryPath = '/assistant/memory'
export const readMemory = () => api<AssistantMemory>(memoryPath)
export const memoryResource = () =>
  sharedResource(
    `memory:${queryIdentity}`,
    (evict) => new QueryResource((signal) => api<AssistantMemory>(memoryPath, { signal }), evict),
  )
export const saveMemorySettings = (enabled: boolean, expectedRevision: number) =>
  write<AssistantMemory>(`${memoryPath}/settings`, { enabled, expectedRevision }, 'PATCH')
export const saveMemoryDocument = (markdown: string, expectedRevision: number) =>
  write<AssistantMemory>(`${memoryPath}/document`, { markdown, expectedRevision }, 'PUT')
export const clearMemoryDocument = (expectedRevision: number) =>
  api<AssistantMemory>(`${memoryPath}/document?expectedRevision=${expectedRevision}`, {
    method: 'DELETE',
  })
