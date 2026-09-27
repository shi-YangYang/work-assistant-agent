import styles from './AppRoutes.module.css'
import type { Identity } from '@paa/api-contracts'
import { Component, Suspense, lazy, useState, type ComponentType, type ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router'

class RouteFailure extends Component<
  { children: ReactNode; retry: () => void },
  { failed: boolean }
> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  render() {
    return this.state.failed ? (
      <div className={styles['route-state']} role="alert">
        <p>页面未能加载，请检查网络后重试。</p>
        <button onClick={this.props.retry}>重新加载页面</button>
      </div>
    ) : (
      this.props.children
    )
  }
}
function routePage<Props extends object>(load: () => Promise<{ default: ComponentType<Props> }>) {
  return function DeferredPage(props: Props) {
    const [attempt, setAttempt] = useState(() => ({ id: 0, Page: lazy(load) }))
    const Page = attempt.Page
    return (
      <RouteFailure
        key={attempt.id}
        retry={() => setAttempt((value) => ({ id: value.id + 1, Page: lazy(load) }))}
      >
        <Suspense
          fallback={
            <div className={styles['route-state']} role="status">
              正在打开页面…
            </div>
          }
        >
          <Page {...props} />
        </Suspense>
      </RouteFailure>
    )
  }
}

const LoginMethods = routePage(async () => ({
  default: (await import('@web/features/auth/components/LoginMethods')).LoginMethods,
}))
const SupportPage = routePage(async () => ({
  default: (await import('@web/features/feedback/components/SupportPage')).SupportPage,
}))
const MembersPage = routePage(async () => ({
  default: (await import('@web/features/members/components/MembersPage')).MembersPage,
}))
const ModelServices = routePage(async () => ({
  default: (await import('@web/features/model-services/components/ModelServices')).ModelServices,
}))
const ModelUsagePage = routePage(async () => ({
  default: (await import('@web/features/model-services/components/ModelUsagePage')).ModelUsagePage,
}))
const AccountPage = routePage(async () => ({
  default: (await import('@web/features/settings/components/AccountPage')).DingTalkAccountPage,
}))
const AppearancePage = routePage(async () => ({
  default: (await import('@web/features/settings/components/AppearancePage')).AppearancePage,
}))
const RulesPage = routePage(async () => ({
  default: (await import('@web/features/settings/components/RulesPage')).RulesPage,
}))
const VoiceprintsPage = routePage(async () => ({
  default: (await import('@web/features/voiceprints/components/VoiceprintsPage')).VoiceprintsPage,
}))
const AssistantPage = routePage(async () => ({
  default: (await import('@web/pages/AssistantPage')).AssistantPage,
}))
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
