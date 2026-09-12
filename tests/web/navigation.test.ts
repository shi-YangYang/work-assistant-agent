import { expect, it } from 'vitest'
import { detailContext, detailReturn, detailState, pageName } from '../../src/web/navigation'

it('preserves the team filters and selected member tab through nested report, work and source pages', () => {
  const team = { pathname: '/team', search: '?q=员工&status=blocked&start=2026-09-01', state: null }
  const member = {
    pathname: '/team/employee',
    search: '?tab=reports&kind=weekly',
    state: detailState(team),
  }
  const report = { pathname: '/reports/report', search: '', state: detailState(member) }
  const work = { pathname: '/work/work', search: '', state: detailState(report) }
  const source = { pathname: '/messages/source', search: '', state: detailState(work) }
  let back = detailReturn(source.pathname, source.state)
  expect(back.path).toBe('/work/work')
  expect(detailContext(back.state)).toBe('团队看板')
  back = detailReturn(back.path, back.state)
  expect(back.path).toBe('/reports/report')
  back = detailReturn(back.path, back.state)
  expect(back.path).toBe('/team/employee?tab=reports&kind=weekly')
  back = detailReturn('/team/employee', back.state)
  expect(back.path).toBe(team.pathname + team.search)
})

it('has deterministic direct-entry fallbacks and rejects external or malformed return paths', () => {
  for (const path of [
    'https://other.test',
    '//other.test',
    '/\\other.test',
    '/unknown',
    '/work/../settings',
    'javascript:alert(1)',
  ]) {
    expect(detailReturn('/messages/source', { returnTo: { path } }).path).toBe('/assistant')
  }
  expect(detailReturn('/work/work', null).path).toBe('/work')
  expect(detailReturn('/reports/report', null).path).toBe('/reports')
  expect(detailReturn('/team/member', null).path).toBe('/team')
  expect(detailReturn('/messages/source', { returnTo: { path: '/messages/source' } }).path).toBe(
    '/assistant',
  )
  expect(pageName('/messages/source')).toBe('原始上报')
})
