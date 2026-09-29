import type {
  AssistantInteraction,
  Attachment,
  BusinessAction,
  Conversation,
  Draft,
  Identity,
  Job,
  Member,
  Report,
  ReportNotification,
  ReportObligation,
  SupportFeedback,
  Work,
  WorkMessage,
} from '@paa/api-contracts'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, setCsrf } from '../../apps/web/src/api/client'
import * as assistant from '../../apps/web/src/features/assistant/api/requests'
import { deliverablePath } from '../../apps/web/src/features/assistant/api/deliverables'
import * as interactions from '../../apps/web/src/features/assistant/api/interactions'
import * as restore from '../../apps/web/src/features/assistant/api/restore-conversation'
import * as auth from '../../apps/web/src/features/auth/api/requests'
import * as feedback from '../../apps/web/src/features/feedback/api/requests'
import * as jobs from '../../apps/web/src/features/jobs/api/requests'
import * as members from '../../apps/web/src/features/members/api/requests'
import * as models from '../../apps/web/src/features/model-services/api/requests'
import * as records from '../../apps/web/src/features/records/api/requests'
import * as reports from '../../apps/web/src/features/reports/api/requests'
import * as settings from '../../apps/web/src/features/settings/api/requests'
import * as sources from '../../apps/web/src/features/sources/api/requests'
import * as team from '../../apps/web/src/features/team/api/requests'
import * as voiceprints from '../../apps/web/src/features/voiceprints/api/requests'
import type { Enrollment } from '../../apps/web/src/features/voiceprints/api/types'
import type { ServiceDraft } from '../../apps/web/src/features/model-services/utils/service-drafts'
import * as work from '../../apps/web/src/features/work/api/requests'

const request = vi.fn<typeof fetch>()
const signal = new AbortController().signal
const conversation = { id: 'chat', revision: 7 } as Conversation
const member = { id: 'member' } as Member
const message = { id: 'message' } as WorkMessage
const record = { id: 'work', revision: 4 } as Work
const report = { id: 'report', revision: 5 } as Report
const action = { id: 'action', revision: 2 } as BusinessAction
const interaction = { id: 'question', revision: 6 } as AssistantInteraction
const draft = { id: 'draft', messageId: 'message' } as Draft
const attachment = { id: 'file' } as Attachment
const service = { id: 'service', revision: 3, models: [] } as unknown as ServiceDraft
const enrollment = { memberId: 'member' } as Enrollment
const revision = { expectedRevision: 7 }
const query = new URLSearchParams({ kind: 'weekly', cursor: 'page & 中', status: 'pending' })

beforeEach(() => {
  vi.stubGlobal(
    'window',
    Object.assign(new EventTarget(), {
      location: { pathname: '/assistant/chat' },
      innerWidth: 1024,
      innerHeight: 768,
    }),
  )
  vi.stubGlobal(
    'fetch',
    request.mockImplementation(() => Promise.resolve(new Response('{}'))),
  )
  setCsrf('request-contract-token')
})
afterEach(() => {
  setCsrf('')
  vi.unstubAllGlobals()
  request.mockReset()
})

type Contract = {
  name: string
  path: string
  method: string
  run: () => Promise<unknown>
  body?: unknown
  key?: string
}
const get = (path: string, run: () => Promise<unknown>, name = path): Contract => ({
  name,
  path,
  method: 'GET',
  run,
})
const path = (expected: string, value: () => string | null, name = expected) =>
  get(expected, () => api(value()!), name)
const write = (
  method: string,
  path: string,
  run: () => Promise<unknown>,
  body?: unknown,
  key?: string,
  name = `${method} ${path}`,
): Contract => ({ name, path, method, run, body, key })

const progress = {
  title: '事项',
  summary: '内容',
  status: 'blocked' as const,
  blocker: '阻碍',
  nextStep: '后续',
  dueDate: null,
}
const reportContent = { completed: '完成', ongoing: '进行中', blockers: '', next: '明日' }
const modelBody = {
  name: '模型服务',
  baseUrl: 'https://example.com/v1',
  models: [],
  expectedRevision: 3,
  apiKey: 'controlled-key',
}
const checkBody = {
  ...modelBody,
  serviceId: 'service',
  modelId: 'model',
  purpose: 'assistant' as const,
  draftVersion: 'draft-v2',
}
const ruleBody: Parameters<typeof settings.saveReportRules>[0] = {
  timezone: 'Asia/Shanghai',
  expectedRevision: 7,
  daily: { enabled: true, days: [1, 2, 3, 4, 5], generateTime: '18:00', deadline: '19:00' },
  weekly: { enabled: false, days: [5], generateTime: '18:00', deadline: '19:00' },
}
const sendBody = { conversationId: 'chat', text: '消息', attachmentIds: ['file'], replyTo: null }
const batch = { items: [{ id: 'draft', expectedRevision: 2 }] }
const answers = [{ questionId: 'field', optionIds: ['option'], text: '补充' }]
const retryBodies: (Record<string, never> | { useCurrentConfig: boolean })[] = [
  {},
  { useCurrentConfig: true },
]

const contracts: Contract[] = [
  get('/auth/providers', () => auth.readLoginProviders({ signal })),
  get('/auth/me', () => auth.readIdentity({ signal })),
  write('POST', '/auth/login', () => auth.login({ username: 'user', password: 'controlled' }), {
    username: 'user',
    password: 'controlled',
  }),
  write('POST', '/auth/logout', () => auth.logout({}), {}),
  path('/settings/login/dingtalk', auth.dingTalkConfigurationPath),
  write(
    'PUT',
    '/settings/login/dingtalk',
    () =>
      auth.saveDingTalkConfiguration({
        corpId: 'corp',
        clientId: 'client',
        secret: 'controlled',
        enabled: true,
        expectedRevision: 7,
      }),
    {
      corpId: 'corp',
      clientId: 'client',
      secret: 'controlled',
      enabled: true,
      expectedRevision: 7,
    },
  ),
  ...(['login', 'probe', 'reauthenticate', 'bind'] as const).map((intent, index) =>
    write(
      'POST',
      [
        '/auth/dingtalk/start',
        '/settings/login/dingtalk/probe',
        '/auth/dingtalk/account/reauth',
        '/auth/dingtalk/account/bind',
      ][index],
      () => auth.startDingTalkRedirect(intent, { companyId: 'company' }),
      { companyId: 'company' },
    ),
  ),
  path('/auth/desktop/requests/request', () => auth.desktopAuthorizationPath(true, 'request')),
  ...[true, false].map((approve) =>
    write(
      'POST',
      '/auth/desktop/requests/request',
      () => auth.resolveDesktopAuthorization('request', { approve }),
      { approve },
      undefined,
      `desktop approve=${approve}`,
    ),
  ),
  path('/auth/dingtalk/account', settings.dingTalkAccountPath),
  ...[false, true].map((useDingTalk) =>
    write(
      'POST',
      '/auth/password',
      () => settings.changePassword({ currentPassword: 'old', newPassword: 'new', useDingTalk }),
      { currentPassword: 'old', newPassword: 'new', useDingTalk },
      undefined,
      `password DingTalk proof=${useDingTalk}`,
    ),
  ),
  write(
    'POST',
    '/auth/dingtalk/account/unbind',
    () => settings.unbindDingTalk({ currentPassword: 'old', useDingTalk: false }),
    { currentPassword: 'old', useDingTalk: false },
  ),
  path('/conversations?q=%E4%B8%AD%E6%96%87%20%26', () => assistant.conversationsPath('中文 &')),
  get('/conversations?q=%E4%B8%AD%E6%96%87%20%26&cursor=page%20%26', () =>
    assistant.readMoreConversations('中文 &', 'page &', signal),
  ),
  get('/conversations?q=', () => assistant.readMoreConversations('', null, signal)),
  path('/conversations/chat', () => assistant.conversationPath('chat')),
  get(
    '/conversations/chat',
    () => assistant.readConversation(conversation),
    'conversation explicit read',
  ),
  get(
    '/conversations/chat',
    () => assistant.readConversationForBreadcrumb('chat', { signal }),
    'conversation breadcrumb read',
  ),
  get('/conversations/chat/deletion', () => assistant.readConversationDeletion(conversation)),
  get('/conversations?order=last_message', () => restore.latestChat(signal)),
  write(
    'PATCH',
    '/conversations/chat',
    () => assistant.renameConversation(conversation, { title: '新标题', expectedRevision: 7 }),
    { title: '新标题', expectedRevision: 7 },
    undefined,
    'rename conversation',
  ),
  write(
    'PATCH',
    '/conversations/chat',
    () =>
      assistant.updateConversationPersona(conversation, {
        personaId: 'professional',
        expectedRevision: 7,
      }),
    { personaId: 'professional', expectedRevision: 7 },
    undefined,
    'conversation persona',
  ),
  write(
    'PATCH',
    '/conversations/chat',
    () => interactions.updateExecutionMode(conversation, 'full', true),
    { executionMode: 'full', fullAccessConfirmed: true, expectedRevision: 7 },
    undefined,
    'conversation execution mode',
  ),
  write(
    'DELETE',
    '/conversations/chat',
    () => assistant.deleteConversation(conversation, revision),
    revision,
  ),
  path('/messages?conversationId=chat', () => assistant.conversationMessagesPath('chat')),
  path('/messages/message', () => assistant.messagePath('message')),
  get('/messages/message', () => assistant.readMessageForBreadcrumb('message', { signal })),
  write(
    'POST',
    '/messages',
    () => assistant.sendMessage(sendBody, 'send-key'),
    sendBody,
    'send-key',
  ),
  write(
    'PATCH',
    '/messages/message/transcript',
    () => assistant.correctTranscript(message, { text: '正确转写', expectedRevision: 7 }),
    { text: '正确转写', expectedRevision: 7 },
  ),
  get('/conversations/chat/active-job', () => assistant.readActiveAssistantJob('chat', signal)),
  get('/conversations/chat/context-usage', () => assistant.readConversationContext('chat', signal)),
  path('/business-actions?conversationId=chat&orphanOnly=true', () =>
    assistant.orphanActionsPath('chat'),
  ),
  ...(['confirm', 'cancel'] as const).map((choice) =>
    write(
      'POST',
      `/business-actions/action/${choice}`,
      () => assistant.resolveBusinessAction(action, choice, revision),
      revision,
    ),
  ),
  path('/conversations/chat/interactions', () => interactions.conversationInteractionsPath('chat')),
  write(
    'POST',
    '/interactions/question/answer',
    () => interactions.answerInteraction(interaction, answers, 'answer-key'),
    { expectedRevision: 6, answers },
    'answer-key',
  ),
  write(
    'POST',
    '/interactions/question/cancel',
    () => interactions.cancelInteraction(interaction, 'cancel-key'),
    { expectedRevision: 6 },
    'cancel-key',
  ),
  path('/deliverables/item%2Fone?revision=3', () => deliverablePath('item/one', 3)),
  path('/uploads/file/extraction?start=20&revision=3', () =>
    assistant.documentExtractionPath('file', 20, 3),
  ),
  path('/uploads/file/extraction?start=0', () =>
    assistant.documentExtractionPath('file', 0, undefined),
  ),
  write('POST', '/uploads/file/retry', () => assistant.retryDocument(attachment, {}), {}),
  path('/work-items?q=%E4%B8%AD%E6%96%87%20%26', () => assistant.referenceWorksPath('中文 &')),
  get('/work-items/work%2Fone', () => assistant.readReferenceWork('work/one', signal)),
  get('/jobs/job/feedback', () => api('/jobs/job/feedback', { signal })),
  ...retryBodies.map((body) =>
    write(
      'POST',
      '/jobs/job/retry',
      () => jobs.retryJob({ id: 'job' } as Job, body),
      body,
      undefined,
      `retry current configuration=${'useCurrentConfig' in body}`,
    ),
  ),
  write(
    'POST',
    '/jobs/job/cancel',
    () => jobs.cancelJob({ id: 'job', attempt: 2, fence: 9 } as Job),
    { expectedAttempt: 2, expectedFence: 9 },
  ),
  path('/work-items', work.availableWorkPath),
  path('/work-items?q=%E4%B8%AD%E6%96%87+%26&status=blocked', () =>
    work.workListPath('中文 &', 'blocked'),
  ),
  path('/work-items/work?revision=2', () => work.workDetailPath('work', '?revision=2')),
  get('/work-items/work', () => work.readWork(record)),
  get(
    '/work-items/work',
    () => work.readWorkForBreadcrumb('work', { signal }),
    'work breadcrumb read',
  ),
  write('POST', '/work-items', () => work.createWork(progress, 'work-key'), progress, 'work-key'),
  write(
    'POST',
    '/work-items/work/progress',
    () =>
      work.updateWorkProgress(record, { ...progress, sourceIds: ['message'], expectedRevision: 4 }),
    { ...progress, sourceIds: ['message'], expectedRevision: 4 },
  ),
  write(
    'DELETE',
    '/work-items/work',
    () => records.deleteRecord('work-items', 'work', revision),
    revision,
  ),
  get('/messages/message', () => work.readProgressSource(draft), 'progress source read'),
  write(
    'PATCH',
    '/progress-drafts/draft',
    () => work.updateProgressDraft(draft, { ...progress, workId: null, expectedRevision: 2 }),
    { ...progress, workId: null, expectedRevision: 2 },
  ),
  ...(['confirm', 'ignore'] as const).map((choice) =>
    write(
      'POST',
      `/progress-drafts/${choice}`,
      () => assistant.resolveProgressDrafts(choice, batch, 'batch-key'),
      batch,
      'batch-key',
    ),
  ),
  path('/reports?kind=daily', () => reports.reportListPath(false, 'daily')),
  path('/reports?kind=weekly', () => reports.reportListPath(false, 'weekly')),
  path('/reports/report?revision=2', () => reports.reportDetailPath('report', '?revision=2')),
  get('/reports/report', () => reports.readReport('report')),
  get(
    '/reports/report',
    () => reports.readReportForBreadcrumb('report', { signal }),
    'report breadcrumb read',
  ),
  path('/reports/report/sources?revision=5', () => reports.reportSourcesPath(report)),
  path('/reports/report/deletion', () => records.deletionImpactPath('reports', 'report')),
  write(
    'POST',
    '/reports/generate',
    () => reports.generateReport({ kind: 'weekly', date: '2026-09-29' }, 'report-key'),
    { kind: 'weekly', date: '2026-09-29' },
    'report-key',
  ),
  write(
    'PATCH',
    '/reports/report',
    () => reports.updateReport('report', { content: reportContent, expectedRevision: 5 }),
    { content: reportContent, expectedRevision: 5 },
  ),
  write(
    'POST',
    '/reports/report/candidate',
    () => reports.generateReportCandidate('report', revision),
    revision,
  ),
  write(
    'POST',
    '/reports/report/submit',
    () => reports.submitReport('report', revision, 'submit-key'),
    revision,
    'submit-key',
  ),
  write(
    'DELETE',
    '/reports/report',
    () => records.deleteRecord('reports', 'report', revision),
    revision,
  ),
  ...[false, true].map((isTeam) =>
    path(`${isTeam ? '/team' : ''}/report-obligations?${query}`, () =>
      reports.reportObligationsPath(isTeam, query),
    ),
  ),
  write(
    'POST',
    '/report-obligations/obligation/prepare',
    () => reports.prepareReport({ id: 'obligation' } as ReportObligation, {}, 'prepare-key'),
    {},
    'prepare-key',
  ),
  path('/notifications?cursor=page', () =>
    reports.notificationsPath({ member: { role: 'employee' } } as Identity, 'page'),
  ),
  write(
    'POST',
    '/notifications/notification/read',
    () => reports.markNotificationRead({ id: 'notification' } as ReportNotification, {}),
    {},
  ),
  ...(['work', 'reports'] as const).map((view) =>
    path(`/team/workspace/${view}?${query}`, () => team.teamWorkspacePath(view, query)),
  ),
  get('/team/members/member/work', () => team.readMemberForBreadcrumb('member', { signal })),
  path('/business-sources/message/token', () => `${sources.messageSourcesPath('message')}/token`),
  path('/work-items/work/business-sources/token', () => `${sources.workSourcesPath('work')}/token`),
  path('/members', members.membersPath),
  path('/members/member/deletion', () => members.memberDeletionPath(member)),
  write(
    'POST',
    '/members',
    () =>
      members.createMember({
        name: '员工',
        username: 'user',
        role: 'employee',
        password: 'controlled',
      }),
    { name: '员工', username: 'user', role: 'employee', password: 'controlled' },
  ),
  write('PATCH', '/members/member', () => members.updateMember(member, { active: false }), {
    active: false,
  }),
  write(
    'POST',
    '/members/member/reset-password',
    () => members.resetMemberPassword(member, { password: 'controlled' }),
    { password: 'controlled' },
  ),
  write('DELETE', '/members/member', () => members.deleteMember(member, undefined)),
  path('/settings/report-rules', settings.reportRulesPath),
  path('/settings/report-rules', reports.reportRulesPath, 'report overview rules'),
  get('/settings/report-rules', settings.readReportRules, 'explicit report rules read'),
  write('PUT', '/settings/report-rules', () => settings.saveReportRules(ruleBody), ruleBody),
  path('/settings/model-services', models.modelServicesPath),
  get('/settings/model-services/service', () => models.readModelService(service)),
  get('/settings/model-routing', models.readModelRouting),
  write(
    'PUT',
    '/settings/model-routing',
    () =>
      models.saveModelRouting({
        assistant: null,
        report: 'follow',
        asr: null,
        expectedRevision: 3,
      }),
    { assistant: null, report: 'follow', asr: null, expectedRevision: 3 },
  ),
  write(
    'POST',
    '/settings/model-services',
    () => models.saveModelService({ ...service, revision: 0 }, modelBody, 'POST'),
    modelBody,
  ),
  write(
    'PATCH',
    '/settings/model-services/service',
    () => models.saveModelService(service, modelBody, 'PATCH'),
    modelBody,
  ),
  write(
    'DELETE',
    '/settings/model-services/service',
    () => models.deleteModelService(service, revision),
    revision,
  ),
  ...(['models', 'test'] as const).map((kind) =>
    write(
      'POST',
      `/settings/model-services/${kind}`,
      () => models.checkServiceConfiguration(kind, checkBody),
      checkBody,
    ),
  ),
  write(
    'POST',
    '/settings/model-services/import-environment',
    () => models.importEnvironmentServices({}),
    {},
  ),
  path(`/settings/model-usage?${query}`, () => models.modelUsagePath(query)),
  path('/support-feedback?scope=mine', () => feedback.feedbackListPath('mine', '')),
  path('/support-feedback?scope=all&state=resolved', () =>
    feedback.feedbackListPath('all', 'resolved'),
  ),
  get('/support-feedback/feedback', () =>
    feedback.readFeedback({ id: 'feedback' } as SupportFeedback),
  ),
  write(
    'POST',
    '/support-feedback',
    () =>
      feedback.submitFeedback(
        { description: '问题描述', diagnostics: { page: '/support' } },
        'feedback-key',
      ),
    { description: '问题描述', diagnostics: { page: '/support' } },
    'feedback-key',
  ),
  write(
    'PATCH',
    '/support-feedback/feedback',
    () =>
      feedback.handleFeedback({ id: 'feedback' } as SupportFeedback, {
        state: 'resolved',
        handlingNote: '已处理',
        expectedRevision: 7,
      }),
    { state: 'resolved', handlingNote: '已处理', expectedRevision: 7 },
  ),
  path('/settings/voiceprints', voiceprints.voiceprintsPath),
  path('/settings/voiceprints/cleanup', voiceprints.voiceprintCleanupPath),
  write('POST', '/settings/voiceprints/cleanup', voiceprints.cleanupVoiceprints, {}),
  write(
    'POST',
    '/settings/voiceprints/member/retry',
    () => voiceprints.manageVoiceprint(enrollment, 'retry', {}, 'POST'),
    {},
  ),
  write(
    'DELETE',
    '/settings/voiceprints/member',
    () => voiceprints.manageVoiceprint(enrollment, 'delete', {}, 'DELETE'),
    {},
  ),
]

it.each(contracts)('$method $name preserves its request contract', async (contract) => {
  request.mockResolvedValue(new Response(JSON.stringify({ items: [], id: 'chat' })))
  await contract.run()
  expect(request).toHaveBeenCalledTimes(1)
  const [url, options] = request.mock.calls[0]
  expect(url).toBe('/api/v1' + contract.path)
  expect(options?.method ?? 'GET').toBe(contract.method)
  expect(options?.credentials).toBe('same-origin')
  const headers = new Headers(options?.headers)
  if (contract.method !== 'GET') expect(headers.get('X-CSRF-Token')).toBe('request-contract-token')
  expect(headers.get('Idempotency-Key')).toBe(contract.key ?? null)
  expect(options?.body === undefined ? undefined : JSON.parse(String(options.body))).toEqual(
    contract.body,
  )
})

it.each(['attachment', 'voiceprint'] as const)(
  'uploads %s as unchanged multipart data',
  async (kind) => {
    const form = new FormData()
    form.append('file', new Blob(['controlled file']), 'fixture.txt')
    form.append('expectedRevision', '2')
    const options = { method: 'POST', body: form, signal }
    if (kind === 'attachment') await assistant.uploadAttachment(options)
    else await voiceprints.uploadVoiceprint(enrollment, options)
    expect(request).toHaveBeenCalledTimes(1)
    const [url, sent] = request.mock.calls[0]
    expect(url).toBe(
      `/api/v1${kind === 'attachment' ? '/uploads' : '/settings/voiceprints/member'}`,
    )
    expect(sent?.method).toBe('POST')
    expect(sent?.body).toBe(form)
    expect(sent?.credentials).toBe('same-origin')
    expect(new Headers(sent?.headers).get('Content-Type')).toBeNull()
    expect(new Headers(sent?.headers).get('X-CSRF-Token')).toBe('request-contract-token')
  },
)

it('downloads authenticated bytes without JSON parsing or changing the full media URL', async () => {
  const bytes = new Uint8Array([0, 12, 255, 80])
  request.mockResolvedValue(new Response(bytes))
  const result = await assistant.readAttachmentBytes('/api/v1/uploads/file/content?revision=2', {
    signal,
  })
  expect(new Uint8Array(result)).toEqual(bytes)
  expect(request.mock.calls[0][0]).toBe('/api/v1/uploads/file/content?revision=2')
  expect(request.mock.calls[0][1]?.credentials).toBe('same-origin')
})

it('keeps disabled or nonexistent resource paths silent', () => {
  expect(assistant.conversationPath(undefined)).toBeNull()
  expect(assistant.conversationMessagesPath(undefined)).toBeNull()
  expect(assistant.orphanActionsPath(undefined)).toBeNull()
  expect(interactions.conversationInteractionsPath(undefined)).toBeNull()
  expect(auth.desktopAuthorizationPath(false, 'invalid')).toBeNull()
  expect(records.deletionImpactPath('work-items', 'work')).toBeNull()
  expect(reports.reportListPath(true, 'daily')).toBeNull()
  expect(reports.notificationsPath({ member: { role: 'admin' } } as Identity, '')).toBeNull()
  expect(request).not.toHaveBeenCalled()
})
