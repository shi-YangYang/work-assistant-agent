import type {
  Announcement,
  AnnouncementContent,
  AnnouncementSummary,
  Page,
} from '@paa/api-contracts'
import { api, write, epoch, queryIdentity } from '@web/api/client'
import { QueryResource, sharedResource } from '@web/lib/query-resource'

export function announcementListPath(state = 'published', cursor = '0') {
  return `/announcements?${new URLSearchParams({ state, cursor })}`
}
export function announcementDetailPath(id: string, management = false) {
  return `/announcements/${encodeURIComponent(id)}?management=${management}`
}
export function announcementList(state: string, cursor: string) {
  const path = announcementListPath(state, cursor)
  return sharedResource(
    `announcements:${epoch}:${queryIdentity}:${path}`,
    (evict) =>
      new QueryResource<Page<AnnouncementSummary>>((signal) => api(path, { signal }), evict),
  )
}
export function publishAnnouncement(body: AnnouncementContent, key: string) {
  return write<Announcement>('/announcements', body, 'POST', key)
}
export function editAnnouncement(id: string, body: AnnouncementContent, expectedRevision: number) {
  return write<Announcement>(
    `/announcements/${encodeURIComponent(id)}`,
    { ...body, expectedRevision },
    'PATCH',
  )
}
export function deleteAnnouncement(id: string, expectedRevision: number, key: string) {
  return write<{ ok: boolean }>(
    `/announcements/${encodeURIComponent(id)}`,
    { expectedRevision },
    'DELETE',
    key,
  )
}
export function markAnnouncementRead(id: string, expectedRevision: number) {
  return write<{ ok: boolean }>(`/announcements/${encodeURIComponent(id)}/read`, {
    expectedRevision,
  })
}

export function readAnnouncement(id: string) {
  return api<Announcement>(announcementDetailPath(id, true))
}
