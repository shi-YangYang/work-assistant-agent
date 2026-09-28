// @vitest-environment jsdom
import type { Identity } from '@paa/api-contracts'
import { createElement } from 'react'
import { cleanup, render as mount, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, expect, it, vi } from 'vitest'
import { AppRoutes } from '../../apps/web/src/app/AppRoutes'

// Keep routing real while replacing page data loading with visible page markers.
vi.mock('@web/pages/AssistantPage', () => ({ AssistantPage: () => 'assistant-page' }))
vi.mock('@web/pages/WorkPage', () => ({ WorkPage: () => 'work-page' }))
vi.mock('@web/pages/ReportsPage', () => ({ ReportsPage: () => 'reports-page' }))
vi.mock('@web/pages/TeamPage', () => ({
  TeamWorkspace: () => 'team-page',
  TeamLegacyRedirect: () => 'legacy-team',
}))
vi.mock('@web/features/members/components/MembersPage', () => ({
  MembersPage: () => 'members-page',
}))
vi.mock('@web/features/model-services/components/ModelServices', () => ({
  ModelServices: () => 'model-services-page',
}))
vi.mock('@web/features/voiceprints/components/VoiceprintsPage', () => ({
  VoiceprintsPage: () => 'voiceprints-page',
}))
vi.mock('@web/features/settings/components/AccountPage', () => ({
  DingTalkAccountPage: () => 'account-page',
}))
vi.mock('@web/features/auth/components/LoginMethods', () => ({
  LoginMethods: () => 'login-methods-page',
}))
vi.mock('@web/features/model-services/components/ModelUsagePage', () => ({
  ModelUsagePage: () => 'model-usage-page',
}))

afterEach(cleanup)
function render(path: string, role: 'admin' | 'employee') {
  const identity = { member: { id: 'member', role } } as Identity
  return mount(
    createElement(
      MemoryRouter,
      { initialEntries: [path] },
      createElement(AppRoutes, {
        identity,
        onLogout: vi.fn(),
      }),
    ),
  )
}
it.each([
  ['/team', 'team-page'],
  ['/members', 'members-page'],
  ['/settings/models', 'model-services-page'],
  ['/settings/voiceprints', 'voiceprints-page'],
  ['/settings/login', 'login-methods-page'],
  ['/settings/usage', 'model-usage-page'],
])('renders administrator route %s only for the administrator', async (path, marker) => {
  render(path, 'admin')
  expect(await screen.findByText(marker)).toBeTruthy()
  cleanup()
  render(path, 'employee')
  expect(
    await screen.findByText(path.startsWith('/settings/') ? 'account-page' : 'assistant-page'),
  ).toBeTruthy()
  expect(screen.queryByText(marker)).toBeNull()
})
it('retains employee reports and shared assistant/work routes', async () => {
  render('/reports', 'employee')
  expect(await screen.findByText('reports-page')).toBeTruthy()
  cleanup()
  render('/reports', 'admin')
  expect(await screen.findByText('team-page')).toBeTruthy()
  expect(screen.queryByText('reports-page')).toBeNull()
  cleanup()
  for (const role of ['admin', 'employee'] as const) {
    render('/assistant/current', role)
    expect(await screen.findByText('assistant-page')).toBeTruthy()
    cleanup()
    render('/work', role)
    expect(await screen.findByText('work-page')).toBeTruthy()
    cleanup()
  }
})
