import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium, webkit, expect } from '@playwright/test'

export const output = resolve(
  process.env.SPEC073_OUTPUT || 'artifacts/spec073/20261017-015130-b9afe2a/assistant',
)
export const origin = process.env.SPEC073_UI || 'http://127.0.0.1:5174'
export const timestamp = '2026-10-17T01:00:00Z'
export const png = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aavcAAAAASUVORK5CYII=',
  'base64',
)
export const previewPng = Buffer.from(
  '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',
  'base64',
)
export const imageSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="800" height="800"><rect width="800" height="800" fill="#bde1f4"/><circle cx="400" cy="360" r="210" fill="#e8d6b9"/><path d="M235 220L190 45L350 170M460 170L625 45L585 230" fill="#e8d6b9"/><circle cx="330" cy="350" r="18"/><circle cx="475" cy="350" r="18"/><text x="400" y="680" text-anchor="middle" font-size="36">合成图片 · UI审计</text></svg>`
export function wav(seconds = 2) {
  const data = Buffer.alloc(44 + seconds * 16000 * 2)
  data.write('RIFF')
  data.writeUInt32LE(data.length - 8, 4)
  data.write('WAVEfmt ', 8)
  data.writeUInt32LE(16, 16)
  data.writeUInt16LE(1, 20)
  data.writeUInt16LE(1, 22)
  data.writeUInt32LE(16000, 24)
  data.writeUInt32LE(32000, 28)
  data.writeUInt16LE(2, 32)
  data.writeUInt16LE(16, 34)
  data.write('data', 36)
  data.writeUInt32LE(data.length - 44, 40)
  for (let n = 0; n < seconds * 16000; n++)
    data.writeInt16LE(Math.sin((n * 2 * Math.PI * 440) / 16000) * 3000, 44 + n * 2)
  return data
}
export const conversation = (id = 'audit-chat') => ({
  id,
  title: '关于长期项目进度与文件整理的会话',
  revision: 1,
  personaId: 'dabao',
  updatedAt: timestamp,
})
export const usage = {
  jobId: 'audit-job',
  attempt: 1,
  fence: 1,
  seq: 1,
  model: 'deepseek-v4.1-flash',
  usedTokens: 23937,
  contextWindow: 1000000,
  inputLimit: 1000000,
  outputReserve: 4000,
  capacitySource: '服务官方规格',
  thresholdRatio: 0.9,
  estimated: true,
  state: 'ready',
  updatedAt: timestamp,
}
export const job = (patch = {}) => ({
  id: 'audit-job',
  kind: 'message',
  targetId: 'audit-message',
  state: 'succeeded',
  phase: 'complete',
  stage: 'complete',
  attempt: 1,
  fence: 1,
  error: '',
  updatedAt: timestamp,
  nodes: [],
  contextUsage: usage,
  ...patch,
})
export const attachment = (kind, id, name) => ({
  id,
  kind,
  name,
  size: 12000,
  mime: kind === 'audio' ? 'audio/wav' : kind === 'image' ? 'image/png' : 'text/plain',
  duration: kind === 'audio' ? 2 : null,
  url: '/api/v1/audit-assets/' + id,
  previewUrl: kind === 'image' ? '/api/v1/audit-assets/' + id : null,
  image: kind === 'image' ? { width: 800, height: 800, warnings: [] } : null,
  extraction:
    kind === 'document'
      ? { status: 'ready', revision: 1, parserVersion: 'audit', characters: 200, chunks: 1 }
      : null,
})
export const message = (patch = {}) => ({
  id: 'audit-message',
  ownerId: 'audit-owner',
  conversationId: 'audit-chat',
  text: '帮我整理这些合成资料，并给出清晰的行动建议。',
  reply: '整理好了。优先核对关键资料，再完成下一步工作。',
  replyTo: null,
  transcript: '',
  transcriptRevision: 0,
  createdAt: timestamp,
  attachments: [],
  drafts: [],
  suggestions: [],
  deliverables: [],
  job: job(),
  ...patch,
})
export function state() {
  return {
    role: 'employee',
    conversations: [
      conversation(),
      ...Array.from({ length: 7 }, (_, n) => ({
        ...conversation('history-' + n),
        title: n === 0 ? '超长会话名称'.repeat(20) : '资料分析与周报 ' + (n + 1),
      })),
    ],
    messages: [],
    reasoning: {
      options: ['low', 'high', 'max'].map((effort) => ({ effort })),
      selected: { effort: 'high' },
      preferenceRevision: 1,
      configVersion: 'audit-v1',
    },
    execution: { executionMode: 'full', fullAccessConfirmed: true, modeRevision: 1 },
    uploads: new Map(),
    uploadDelay: 0,
    uploadFailures: 0,
    failSend: false,
    log: [],
    unhandled: [],
    errors: [],
  }
}
export async function launch({
  browserName = 'chromium',
  width = 390,
  height = 844,
  theme = 'light',
  motion = 'no-preference',
  pet = false,
  role = 'employee',
  record = false,
} = {}) {
  await mkdir(output, { recursive: true })
  const browser = await (browserName === 'webkit' ? webkit : chromium).launch(
    browserName === 'chromium'
      ? { args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] }
      : {},
  )
  const context = await browser.newContext({
    viewport: { width, height },
    isMobile: true,
    hasTouch: true,
    colorScheme: theme,
    reducedMotion: motion,
    permissions: browserName === 'chromium' ? ['microphone'] : [],
    ...(record
      ? { recordVideo: { dir: resolve(output, 'recordings'), size: { width, height } } }
      : {}),
  })
  await context.addInitScript(
    ({ theme, pet }) => {
      localStorage.setItem('paa.company.theme', theme)
      localStorage.setItem('paa.company.pet-visible', String(pet))
      window.auditSources = []
      class Source extends EventTarget {
        constructor(url) {
          super()
          this.url = url
          this.closed = false
          window.auditSources.push(this)
        }
        close() {
          this.closed = true
        }
      }
      window.EventSource = Source
    },
    { theme, pet },
  )
  const page = await context.newPage()
  const s = state()
  s.role = role
  page.on('pageerror', (e) => s.errors.push(e.message))
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request(),
      url = new URL(request.url()),
      path = url.pathname.slice(7),
      method = request.method()
    s.log.push({ path, method })
    let data
    const body = () => request.postDataJSON()
    if (path.startsWith('/deliverables/images/files/')) {
      if (s.imageDelay) await new Promise((r) => setTimeout(r, s.imageDelay))
      return route.fulfill({ contentType: 'image/png', body: previewPng })
    }
    if (path.startsWith('/audit-assets/')) {
      const id = path.split('/').at(-1)
      return route.fulfill({
        contentType: id.startsWith('audio') ? 'audio/wav' : 'image/svg+xml',
        body: id.startsWith('audio') ? wav() : imageSvg,
      })
    }
    if (path === '/auth/me')
      data = {
        csrf: 'synthetic-audit-token',
        company: { id: 'audit-company', name: '手机UI审计公司' },
        member: {
          id: 'audit-owner',
          name: '手机审计用户',
          username: 'ui-audit',
          role: s.role,
          active: true,
          hasPassword: true,
        },
      }
    else if (path === '/notification-summary')
      data = { remindersUnread: 1, announcementsUnread: 1, totalUnread: 2 }
    else if (path === '/assistant/activity')
      data = {
        jobs: s.messages
          .filter((m) => m.job && ['running', 'queued'].includes(m.job.state))
          .map((m) => ({ ...m.job, conversationId: m.conversationId, seq: 1 })),
      }
    else if (path === '/assistant/reasoning-settings') {
      if (method === 'PATCH')
        s.reasoning = {
          ...s.reasoning,
          selected: { effort: body().effort },
          preferenceRevision: s.reasoning.preferenceRevision + 1,
        }
      data = s.reasoning
    } else if (path === '/assistant/execution-settings') {
      if (method === 'PATCH')
        s.execution = {
          ...s.execution,
          executionMode: body().executionMode,
          modeRevision: s.execution.modeRevision + 1,
        }
      data = s.execution
    } else if (path === '/conversations') {
      data = {
        items: (url.searchParams.has('cursor')
          ? (s.moreConversations ?? [])
          : s.conversations
        ).filter((c) => !url.searchParams.get('q') || c.title.includes(url.searchParams.get('q'))),
        nextCursor:
          !url.searchParams.has('cursor') && s.moreConversations?.length
            ? 'older-conversations'
            : null,
      }
    } else if (/^\/conversations\/[^/]+$/.test(path)) {
      const id = path.split('/')[2]
      if (method === 'DELETE') {
        s.conversations = s.conversations.filter((c) => c.id !== id)
        data = { ok: true }
      } else {
        let c = s.conversations.find((c) => c.id === id) || conversation(id)
        if (method === 'PATCH') {
          c = { ...c, ...body(), revision: c.revision + 1 }
          s.conversations = s.conversations.map((v) => (v.id === id ? c : v))
        }
        data = c
      }
    } else if (path.endsWith('/context-usage')) data = { contextUsage: usage }
    else if (path.endsWith('/active-job'))
      data = {
        job:
          s.messages.find((m) => m.job && ['queued', 'running'].includes(m.job.state))?.job ?? null,
      }
    else if (path.endsWith('/interactions')) data = { items: s.interactions ?? [] }
    else if (path === '/business-actions') data = { items: [] }
    else if (/^\/business-actions\/[^/]+\/(confirm|cancel)$/.test(path)) {
      const action = s.messages
        .flatMap((m) => m.actions ?? [])
        .find((a) => a.id === path.split('/')[2])
      Object.assign(action, {
        state: path.endsWith('/confirm') ? 'succeeded' : 'cancelled',
        canConfirm: false,
        revision: 2,
      })
      data = action
    } else if (/^\/interactions\/[^/]+\/(answer|cancel)$/.test(path)) {
      const item = s.interactions.find((i) => i.id === path.split('/')[2])
      Object.assign(item, {
        state: path.endsWith('/answer') ? 'answered' : 'cancelled',
        answers: body().answers ?? [],
        revision: 2,
      })
      data = { interaction: item }
    } else if (path.endsWith('/deletion')) data = { retainedSources: 0 }
    else if (path === '/messages' && method === 'GET')
      data = {
        items: url.searchParams.has('cursor') ? (s.moreMessages ?? []) : s.messages,
        nextCursor:
          !url.searchParams.has('cursor') && s.moreMessages?.length ? 'older-messages' : null,
      }
    else if (path === '/messages' && method === 'POST') {
      if (s.sendDelay) await new Promise((resolve) => setTimeout(resolve, s.sendDelay))
      if (s.failSend)
        return route.fulfill({
          status: 503,
          json: { error: { code: 'service_unavailable', message: '发送失败，请稍后再试' } },
        })
      const b = body()
      s.lastSend = b
      s.messages = [
        ...s.messages,
        message({
          id: 'sent-' + s.messages.length,
          text: b.text,
          attachments: b.attachmentIds.map((id) => s.uploads.get(id)).filter(Boolean),
        }),
      ]
      data = { conversationId: 'audit-chat', messageId: s.messages.at(-1).id, jobId: 'audit-job' }
    } else if (/^\/messages\/[^/]+\/transcript$/.test(path)) {
      s.messages = s.messages.map((m) =>
        m.id === path.split('/')[2]
          ? { ...m, transcript: body().text, transcriptRevision: m.transcriptRevision + 1 }
          : m,
      )
      data = { ok: true }
    } else if (/^\/messages\/[^/]+$/.test(path))
      data = s.messages.find((m) => m.id === path.split('/')[2]) ?? message()
    else if (path === '/jobs/audit-job') data = s.messages.at(-1)?.job ?? job()
    else if (path === '/jobs/audit-job/cancel') {
      s.messages = s.messages.map((m) => ({
        ...m,
        job: {
          ...m.job,
          state: 'cancelled',
          stage: 'complete',
          fence: 2,
          imageGeneration: m.job?.imageGeneration?.map((slot) => ({ ...slot, state: 'cancelled' })),
        },
      }))
      data = s.messages.at(-1).job
    } else if (path === '/uploads' && method === 'POST') {
      if (s.uploadDelay) await new Promise((r) => setTimeout(r, s.uploadDelay))
      if (s.uploadFailures > 0) {
        s.uploadFailures--
        return route.fulfill({
          status: 503,
          json: { error: { code: 'busy', message: '服务器繁忙，请稍后重试' } },
        })
      }
      const raw = request.postDataBuffer().toString('latin1')
      const name = /filename="([^"]+)"/.exec(raw)?.[1] ?? 'recording.webm'
      const type = /Content-Type: ([^\r\n]+)/.exec(raw)?.[1] ?? 'text/plain'
      const kind = type.startsWith('image/')
        ? 'image'
        : type.startsWith('audio/')
          ? 'audio'
          : 'document'
      const a = attachment(
        kind,
        kind + '-upload-' + s.uploads.size,
        Buffer.from(name, 'latin1').toString(),
      )
      s.uploads.set(a.id, a)
      data = a
    } else if (path.startsWith('/uploads/') && method === 'DELETE') {
      s.uploads.delete(path.split('/')[2])
      data = { ok: true }
    } else if (path === '/work-items')
      data = {
        items: (s.referenceWorks ?? []).filter(
          (work) => !url.searchParams.get('q') || work.title.includes(url.searchParams.get('q')),
        ),
        nextCursor: null,
      }
    else if (/^\/work-items\/[^/]+$/.test(path))
      data = s.referenceWorks?.find((work) => work.id === path.split('/')[2])
    else if (/^\/deliverables\/[^/]+$/.test(path)) data = s.deliverable
    else if (path === '/reminders' || path === '/announcements')
      data = { items: [], nextCursor: null }
    else if (path.endsWith('/sources')) data = { items: [], nextCursor: null }
    else {
      s.unhandled.push({ path, method })
      return route.fulfill({
        status: 501,
        json: { error: { code: 'audit_unhandled', message: '审计夹具未覆盖此请求' } },
      })
    }
    return route.fulfill({ json: data })
  })
  return {
    browser,
    context,
    page,
    s,
    env: { browser: browserName, viewport: { width, height }, theme, motion, role },
    async close() {
      await context.close()
      await browser.close()
    },
  }
}
export async function screenshot(run, index, id, stateName, notes = '') {
  const name = `${String(index.length + 1).padStart(3, '0')}-${id}-${run.env.browser}-${run.env.viewport.width}x${run.env.viewport.height}-${run.env.theme}-${stateName}.png`
  await run.page.screenshot({ path: resolve(output, name) })
  const geometry = await run.page.evaluate(() => ({
    viewport: { width: innerWidth, height: innerHeight },
    documentWidth: document.documentElement.scrollWidth,
    dialogs: [...document.querySelectorAll('[role="dialog"],dialog[open]')].map((e) => ({
      name: e.getAttribute('aria-label') || e.textContent.slice(0, 50),
      box: e.getBoundingClientRect().toJSON(),
    })),
    smallTargets: [...document.querySelectorAll('button,a,input,textarea')]
      .map((e) => ({
        name: e.getAttribute('aria-label') || e.textContent.trim().slice(0, 45),
        box: e.getBoundingClientRect().toJSON(),
      }))
      .filter(
        ({ box }) =>
          box.width &&
          box.height &&
          box.y >= 0 &&
          box.y < innerHeight &&
          (box.width < 44 || box.height < 44),
      ),
  }))
  index.push({
    caseId: id,
    state: stateName,
    route: new URL(run.page.url()).pathname,
    ...run.env,
    dataMode: 'controlled-ui',
    status: 'CAPTURED',
    evidence: name,
    reviewedBy: null,
    visualVerdict: null,
    notes,
    geometry,
  })
  await writeFile(resolve(output, 'screenshot-index.json'), JSON.stringify(index, null, 2))
  return name
}
export { expect }
