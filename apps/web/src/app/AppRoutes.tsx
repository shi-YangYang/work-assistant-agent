import styles from './AppRoutes.module.css'
import type { Identity } from '@paa/api-contracts'
import { routePage } from './route-page'
import { Navigate, Route, Routes } from 'react-router'

const NotificationsPage = routePage(async () => ({
  default: (await import('@web/pages/NotificationsPage')).NotificationsPage,
}))
const AnnouncementManagementPage = routePage(async () => ({
  default: (await import('@web/features/announcements/components/AnnouncementManagementPage'))
    .AnnouncementManagementPage,
}))
const AnnouncementDetail = routePage(async () => ({
  default: (await import('@web/features/announcements/components/AnnouncementDetail'))
    .AnnouncementDetail,
}))
const AnnouncementEditor = routePage(async () => ({
  default: (await import('@web/features/announcements/components/AnnouncementEditor'))
    .AnnouncementEditor,
}))
const LoginMethods = routePage(async () => ({
  default: (await import('@web/features/auth/components/configuration/LoginMethods')).LoginMethods,
}))
const SupportPage = routePage(async () => ({
  default: (await import('@web/features/feedback/components/SupportPage')).SupportPage,
}))
const MembersPage = routePage(async () => ({
  default: (await import('@web/features/members/components/overview/MembersPage')).MembersPage,
}))
const ModelServices = routePage(async () => ({
  default: (await import('@web/features/model-services/components/ModelServices')).ModelServices,
}))
const ModelUsagePage = routePage(async () => ({
  default: (await import('@web/features/model-services/components/usage/ModelUsagePage'))
    .ModelUsagePage,
}))
const AccountPage = routePage(async () => ({
  default: (await import('@web/features/settings/components/account/AccountPage'))
    .DingTalkAccountPage,
}))
const AppearancePage = routePage(async () => ({
  default: (await import('@web/features/settings/components/appearance/AppearancePage'))
    .AppearancePage,
}))
const MemoryPage = routePage(async () => ({
  default: (await import('@web/features/settings/components/memory/MemoryPage')).MemoryPage,
}))
const RulesPage = routePage(async () => ({
  default: (await import('@web/features/settings/components/rules/RulesPage')).RulesPage,
}))
const VoiceprintsPage = routePage(async () => ({
  default: (await import('@web/features/voiceprints/components/VoiceprintsPage')).VoiceprintsPage,
}))
const AssistantPage = routePage(
  async () => ({ default: (await import('@web/pages/AssistantPage')).AssistantPage }),
  { waitForContent: true },
)
const ReportDetailPage = routePage(async () => ({
  default: (await import('@web/pages/ReportDetailPage')).ReportDetailPage,
}))
const ReportsPage = routePage(async () => ({
  default: (await import('@web/pages/ReportsPage')).ReportsPage,
}))
const SourcePage = routePage(async () => ({
  default: (await import('@web/pages/SourcePage')).SourcePage,
}))
const TeamLegacyRedirect = routePage(async () => ({
  default: (await import('@web/pages/TeamPage')).TeamLegacyRedirect,
}))
const TeamWorkspace = routePage(async () => ({
  default: (await import('@web/pages/TeamPage')).TeamWorkspace,
}))
const WorkDetailPage = routePage(async () => ({
  default: (await import('@web/pages/WorkDetailPage')).WorkDetailPage,
}))
const WorkPage = routePage(async () => ({
  default: (await import('@web/pages/WorkPage')).WorkPage,
}))

export function AppRoutes({ identity, onLogout }: { identity: Identity; onLogout: () => void }) {
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
      <Route path="/notifications" element={<NotificationsPage />} />
      <Route path="/notifications/announcements/:id" element={<AnnouncementDetail />} />
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
          <Route path="/announcement-management" element={<AnnouncementManagementPage />} />
          <Route path="/announcement-management/new" element={<AnnouncementEditor />} />
          <Route path="/announcement-management/:id" element={<AnnouncementDetail management />} />
          <Route path="/announcement-management/:id/edit" element={<AnnouncementEditor />} />
          <Route path="/members" element={<MembersPage />} />
        </>
      )}
      <Route
        path="/settings/*"
        element={
          <div className={styles['settings-layout']} data-scroll-container>
            <Routes>
              <Route
                path="account"
                element={<AccountPage member={identity.member} onLogout={onLogout} />}
              />
              <Route path="support" element={<SupportPage />} />
              <Route path="appearance" element={<AppearancePage />} />
              <Route path="memory" element={<MemoryPage />} />
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
