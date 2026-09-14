import { describe, expect, it } from 'vitest'
import type { Page } from '../../src/shared/company-contracts'
import { ApiError } from '../../src/web/api'
import { PagedResource } from '../../src/web/paged-resource'

type Row = { id: string; createdAt: string; period: string; text: string }
const row = (id: number): Row => ({
  id: String(id).padStart(2, '0'),
  createdAt: `2026-09-${String(id).padStart(2, '0')}`,
  period: `2026-09-${String(id).padStart(2, '0')}`,
  text: `正文 ${id}`,
})

function server(initial: Row[]) {
  let rows = initial
  const paths: string[] = []
  const read = async (path: string): Promise<Page<Row>> => {
    paths.push(path)
    const cursor = new URL(path, 'http://test').searchParams.get('cursor')
    if (cursor && !rows.some((item) => item.id === cursor))
      throw new ApiError(404, 'missing', '分页位置已删除')
    const start = cursor ? rows.findIndex((item) => item.id === cursor) + 1 : 0
    const items = rows.slice(start, start + 2)
    return { items, nextCursor: start + 2 < rows.length ? items.at(-1)!.id : null }
  }
  return {
    read,
    paths,
    replace: (next: Row[]) => {
      rows = next
    },
  }
}

describe('loaded page refresh', () => {
  it.each([
    ['/messages?conversationId=own', 'createdAt'],
    ['/team/members/member/messages', 'createdAt'],
    ['/reports?kind=daily', 'period'],
  ] as const)(
    'revalidates old rows and cursor deletions in %s while keeping expanded history',
    async (path, order) => {
      const source = server([8, 7, 6, 5, 4, 3, 2, 1].map(row))
      const resource = new PagedResource<Row>(path, order, source.read)
      await resource.refresh()
      await resource.loadMore()
      expect(resource.getSnapshot().data?.items.map((item) => item.id)).toEqual([
        '08',
        '07',
        '06',
        '05',
      ])
      // Another window deletes the old first-page cursor and the oldest loaded
      // row. New messages push the surviving history beyond two pages.
      source.replace([11, 10, 9, 8, 6, 4, 3, 2, 1].map(row))
      source.paths.length = 0
      await resource.refresh()
      const snapshot = resource.getSnapshot()
      expect(snapshot.error).toBe('')
      expect(snapshot.data?.items.map((item) => item.id)).toEqual([
        '11',
        '10',
        '09',
        '08',
        '06',
        '04',
      ])
      expect(snapshot.data?.items.some((item) => item.text === '正文 5')).toBe(false)
      expect(source.paths).toHaveLength(3)
      expect(source.paths.every((url) => url.startsWith(path))).toBe(true)
      expect(source.paths.some((url) => url.includes('cursor=07'))).toBe(false)
      await resource.loadMore()
      expect(resource.getSnapshot().data?.items.map((item) => item.id)).toContain('02')
    },
  )

  it.each([403, 404])(
    'clears all expanded content when its scope becomes unavailable (%s)',
    async (status) => {
      const source = server([4, 3, 2, 1].map(row))
      let unavailable = false
      const resource = new PagedResource<Row>(
        '/messages?conversationId=deleted',
        'createdAt',
        async (...args) => {
          if (unavailable) throw new ApiError(status, 'missing', '会话已删除')
          return source.read(args[0])
        },
      )
      await resource.refresh()
      await resource.loadMore()
      expect(resource.getSnapshot().data?.items).toHaveLength(4)
      unavailable = true
      await resource.refresh()
      expect(resource.getSnapshot()).toEqual({ data: null, error: '会话已删除', loading: false })
    },
  )

  it('ignores late reads after switching conversations or report filters', async () => {
    let resolve!: (page: Page<Row>) => void
    const previous = new PagedResource<Row>(
      '/messages?conversationId=old',
      'createdAt',
      () =>
        new Promise((done) => {
          resolve = done
        }),
    )
    const pending = previous.refresh()
    previous.dispose()
    const current = new PagedResource<Row>(
      '/messages?conversationId=new',
      'createdAt',
      async () => ({ items: [row(9)] }),
    )
    await current.refresh()
    resolve({ items: [row(1)] })
    await pending
    expect(previous.getSnapshot().data).toBeNull()
    expect(current.getSnapshot().data?.items).toEqual([row(9)])
  })
})
