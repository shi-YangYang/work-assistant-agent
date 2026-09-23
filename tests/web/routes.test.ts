import type { Identity } from '@paa/api-contracts'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { expect, it, vi } from 'vitest'
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
vi.mock('@web/features/auth/components/LoginMethods', () => ({
  LoginMethods: () => 'login-methods-page',
}))
vi.mock('@web/features/model-services/components/ModelUsagePage', () => ({
  ModelUsagePage: () => 'model-usage-page',
}))

function render(path: string, role: 'admin' | 'employee') {
  const identity = { member: { id: 'member', role } } as Identity
  return renderToStaticMarkup(
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
])('renders administrator route %s only for the administrator', (path, marker) => {
  expect(render(path, 'admin')).toContain(marker)
  expect(render(path, 'employee')).not.toContain(marker)
})
it('retains employee reports and shared assistant/work routes', () => {
  expect(render('/reports', 'employee')).toContain('reports-page')
  expect(render('/reports', 'admin')).not.toContain('reports-page')
  for (const role of ['admin', 'employee'] as const) {
    expect(render('/assistant/current', role)).toContain('assistant-page')
    expect(render('/work', role)).toContain('work-page')
  }
})
