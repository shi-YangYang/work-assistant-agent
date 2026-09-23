import styles from './AppRoutes.module.css'
import type { Identity } from '@paa/api-contracts'
import { LoginMethods } from '@web/features/auth/components/LoginMethods'
import { SupportPage } from '@web/features/feedback/components/SupportPage'
import { MembersPage } from '@web/features/members/components/MembersPage'
import { ModelServices } from '@web/features/model-services/components/ModelServices'
import { ModelUsagePage } from '@web/features/model-services/components/ModelUsagePage'
import { DingTalkAccountPage as AccountPage } from '@web/features/settings/components/AccountPage'
import { AppearancePage } from '@web/features/settings/components/AppearancePage'
import { RulesPage } from '@web/features/settings/components/RulesPage'
import { VoiceprintsPage } from '@web/features/voiceprints/components/VoiceprintsPage'
import { AssistantPage } from '@web/pages/AssistantPage'
import { ReportDetailPage } from '@web/pages/ReportDetailPage'
import { ReportsPage } from '@web/pages/ReportsPage'
import { SourcePage } from '@web/pages/SourcePage'
import { TeamLegacyRedirect, TeamWorkspace } from '@web/pages/TeamPage'
import { WorkDetailPage } from '@web/pages/WorkDetailPage'
import { WorkPage } from '@web/pages/WorkPage'
import type { LucideIcon } from 'lucide-react'
import type * as React from 'react'
import { Navigate, NavLink, Route, Routes } from 'react-router'

export function AppRoutes({
  identity,
  allowedSettings,
  setExpandedNav,
  onLogout,
}: {
  identity: Identity
  allowedSettings: (
    | { path: string; title: string; detail: string; icon: LucideIcon; admin: boolean }
    | { path: string; title: string; detail: string; icon: LucideIcon; admin?: undefined }
  )[]
  setExpandedNav: React.Dispatch<React.SetStateAction<boolean>>
  onLogout: () => void
}) {
  return (
    <Routes>
      <Route
        path="/"
        element={
          <Navigate to={identity.member.role === 'admin' ? '/team' : '/assistant'} replace />
        }
      />
      <Route path="/assistant" element={<AssistantPage />} />
      <Route path="/assistant/:conversationId" element={<AssistantPage />} />
      <Route path="/messages/:id" element={<SourcePage />} />
      <Route path="/work" element={<WorkPage />} />
      <Route path="/work/:id" element={<WorkDetailPage />} />
      <Route
        path="/reports"
        element={
          identity.member.role === 'employee' ? <ReportsPage /> : <Navigate to="/team" replace />
        }
      />
      <Route path="/reports/:id" element={<ReportDetailPage />} />
      {identity.member.role === 'admin' && (
        <>
          <Route path="/team" element={<TeamWorkspace />} />
          <Route path="/team/details" element={<TeamLegacyRedirect />} />
          <Route path="/team/reports" element={<TeamLegacyRedirect />} />
          <Route path="/team/:id" element={<TeamLegacyRedirect />} />
          <Route path="/members" element={<MembersPage />} />
        </>
      )}
      <Route
        path="/settings/*"
        element={
          <div className={styles['settings-layout']} data-scroll-container>
            <nav className={styles['settings-nav']} aria-label="设置页面">
              {allowedSettings.map((p) => (
                <NavLink
                  key={p.path}
                  to={p.path}
                  title={p.title}
                  aria-label={p.title}
                  onClick={() => setExpandedNav(false)}
                >
                  {p.title}
                </NavLink>
              ))}
            </nav>
            <Routes>
              <Route
                path="account"
                element={<AccountPage member={identity.member} onLogout={onLogout} />}
              />
              <Route path="support" element={<SupportPage />} />
              <Route path="appearance" element={<AppearancePage />} />
              <Route path="rules" element={<RulesPage />} />
              {identity.member.role === 'admin' && (
                <>
                  <Route path="models" element={<ModelServices />} />
                  <Route path="voiceprints" element={<VoiceprintsPage />} />
                  <Route path="login" element={<LoginMethods />} />
                  <Route path="usage" element={<ModelUsagePage />} />
                </>
              )}
              <Route path="*" element={<Navigate to="/settings/account" replace />} />
            </Routes>
          </div>
        }
      />
      <Route path="*" element={<Navigate to="/assistant" replace />} />
    </Routes>
  )
}
