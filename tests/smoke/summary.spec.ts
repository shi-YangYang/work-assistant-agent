import { test, expect, _electron as electron, type ElectronApplication } from '@playwright/test'
import { createServer, type Server } from 'node:http'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { randomUUID } from 'node:crypto'
import { pythonCommand } from '../../src/desktop/python-command'
import type { ServiceDraft } from '../../src/shared/summary-contracts'

async function close(app: ElectronApplication): Promise<void> {
  await Promise.all([
    app.waitForEvent('close', { timeout: 10000 }),
    app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close()),
  ])
}

test('multi-service settings, custom reasoning, real HTTP checks, minutes sources and restart are portable', async () => {
  test.setTimeout(60000)
  const root = mkdtempSync(join(tmpdir(), 'paa-summary-smoke-'))
  const { command, args } = pythonCommand(resolve('.'))
  const { meetingId } = JSON.parse(
    execFileSync(command, [...args, 'tests/python/summary_fixture.py', root], { encoding: 'utf8' }),
  ) as { meetingId: string }
  const calls: { path: string; body: Record<string, unknown> | null; key: string | undefined }[] =
    []
  let fail = false
  let modelDelay = 0
  let futureIsText = true
  const server: Server = createServer((request, response) => {
    const chunks: Buffer[] = []
    request.on('data', (chunk: Buffer) => chunks.push(chunk))
    request.on('end', () => {
      const input = Buffer.concat(chunks).toString()
      const body = input ? (JSON.parse(input) as Record<string, unknown>) : null
      calls.push({ path: request.url || '', body, key: request.headers.authorization })
      if (request.url === '/v1/models') {
        setTimeout(() => {
          response.writeHead(200, { 'Content-Type': 'application/json' })
          response.end(
            JSON.stringify({
              data: [
                { id: 'future-kimi', output_modalities: [futureIsText ? 'text' : 'image'] },
                { id: 'new-minimax' },
                { id: 'embedding-only', type: 'embedding' },
              ],
            }),
          )
        }, modelDelay)
      } else if (fail) {
        response.writeHead(401)
        response.end('{}')
      } else {
        const messages = body?.messages as { role: string; content: string }[]
        const isSummary = messages.length === 2
        const source = isSummary
          ? (JSON.parse(messages[1].content) as { segments: { id: string; text: string }[] })
          : null
        const content = source
          ? JSON.stringify({
              version: 1,
              title: '上线安排',
              abstract: '最后决定取消上线。',
              topics: ['上线风险'],
              decisions: [{ text: '取消上线', sources: [source.segments.at(-1)?.id] }],
              actions: [
                {
                  task: '核对风险',
                  owner: null,
                  deadline: null,
                  status: null,
                  sources: [source.segments[0].id],
                },
              ],
              risks: [],
              openQuestions: [],
            })
          : '连接成功'
        const payload = { choices: [{ finish_reason: 'stop', message: { content } }] }
        response.writeHead(200, { 'Content-Type': 'application/json' })
        response.end(JSON.stringify(payload))
      }
    })
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const address = server.address()
  if (!address || typeof address === 'string') throw new Error('server missing')
  const baseUrl = `http://127.0.0.1:${address.port}/v1`
  const env = Object.fromEntries(
    Object.entries({ ...process.env, PAA_TEST_DATA_DIR: root, PAA_TEST_ALLOW_HTTP: '1' }).filter(
      (entry): entry is [string, string] => typeof entry[1] === 'string',
    ),
  )
  delete env.ELECTRON_RUN_AS_NODE
  delete env.ELECTRON_RENDERER_URL
  const launch = (): Promise<ElectronApplication> => electron.launch({ args: [resolve('.')], env })
  let app = await launch()
  try {
    let page = await app.firstWindow()
    await expect
      .poll(async () => (await page.evaluate(() => window.paa.getStatus())).connection)
      .toBe('ready')
    const missing = await page.evaluate((id) => window.paa.generateSummary(id), meetingId)
    expect(!missing.ok && missing.code).toBe('not_configured')
    await page.getByRole('button', { name: '设置', exact: true }).click()
    await page.getByRole('button', { name: '模型服务管理', exact: true }).click()
    const card = page.getByLabel('模型服务管理', { exact: true })
    await expect(card.getByLabel('使用流式接口')).toBeChecked()
    // This fixture serves non-streaming JSON responses.
    await card.getByLabel('使用流式接口').uncheck()
    await card.getByLabel('服务名称', { exact: true }).fill('服务甲')
    await card.getByLabel('API Base URL', { exact: true }).fill(baseUrl)
    await card.getByLabel('API 密钥', { exact: true }).fill('fake-only-smoke-key')
    await card.getByRole('button', { name: '获取模型', exact: true }).click()
    await expect(card.getByLabel('可用模型列表')).toBeVisible()
    await expect(
      card.getByRole('option', { name: 'embedding-only · 非文本模型' }),
    ).toHaveJSProperty('disabled', true)
    await card.getByLabel('模型 ID', { exact: true }).fill('embedding-only')
    await expect(card.getByRole('alert')).toContainText('非文本模型')
    await expect(card.getByRole('button', { name: '保存服务', exact: true })).toBeDisabled()
    await expect(card.getByRole('button', { name: '测试连接', exact: true })).toBeDisabled()
    await card.getByLabel('模型 ID', { exact: true }).fill('unknown-manual')
    await card.getByRole('button', { name: '保存服务', exact: true }).click()
    await expect(card.getByText('服务已保存。', { exact: true })).toBeVisible()
    const firstList = await page.evaluate(() => window.paa.listModelServices())
    if (!firstList.ok) throw new Error(firstList.message)
    const profileId = firstList.value.profiles[0].id
    const blockedDraft: ServiceDraft = {
      id: profileId,
      name: '服务甲',
      baseUrl,
      apiKey: '',
      model: 'embedding-only',
      models: [],
      stream: false,
    }
    const rejected = await page.evaluate(
      async (serialized) => ({
        save: await window.paa.saveModelService(JSON.parse(serialized)),
        check: await window.paa.checkModel(JSON.parse(serialized)),
      }),
      JSON.stringify(blockedDraft),
    )
    expect(rejected.save.ok).toBe(false)
    expect(!rejected.save.ok && rejected.save.message).toContain('非文本模型')
    expect(rejected.check.ok).toBe(false)
    expect(calls).toHaveLength(1) // Save/check rejection never performs a paid request.
    await card.getByRole('button', { name: '测试连接', exact: true }).click()
    await expect(card.getByText(/连接成功 ·/)).toBeVisible()
    expect(calls.at(-1)?.body?.model).toBe('unknown-manual')
    await card.getByLabel('可用模型列表').selectOption('future-kimi')
    await card.getByRole('button', { name: '添加推理预设', exact: true }).click()
    await card.getByLabel('预设名称', { exact: true }).fill('深入')
    await card.getByLabel('推理强度值', { exact: true }).fill('future-high')
    await card.getByRole('button', { name: '应用预设', exact: true }).click()
    await card.getByRole('button', { name: '测试连接', exact: true }).click()
    await expect(card.getByText(/连接成功 ·/)).toBeVisible()
    expect(calls.at(-1)?.body?.reasoning_effort).toBe('future-high')
    await card.getByLabel('模型 ID', { exact: true }).fill('new-minimax')
    await expect(card.getByLabel('推理预设', { exact: true })).toHaveValue('')
    await expect(card.getByText(/连接成功 ·/)).toHaveCount(0)
    await card.getByLabel('模型 ID', { exact: true }).fill('future-kimi')
    await expect(card.getByLabel('推理预设', { exact: true })).not.toHaveValue('')
    await card.getByRole('button', { name: '编辑预设', exact: true }).click()
    await card.getByLabel('参数模式').selectOption('advanced')
    await card
      .getByLabel('推理参数 JSON', { exact: true })
      .fill('{"thinking":{"enabled":true,"budget":2048}}')
    await card.getByRole('button', { name: '应用预设', exact: true }).click()
    await card.getByRole('button', { name: '保存服务', exact: true }).click()
    await expect(card.getByText('服务已保存。', { exact: true })).toBeVisible()
    await expect(card.getByLabel('API 密钥', { exact: true })).toHaveValue('')
    await card.getByRole('button', { name: '用于纪要', exact: true }).click()
    await expect(card.getByText('已切换纪要服务。', { exact: true })).toBeVisible()
    const configuration = await page.evaluate(() => window.paa.listModelServices())
    if (!configuration.ok) throw new Error(configuration.message)
    const a = configuration.value.activeProfileId!
    futureIsText = false
    await card.getByRole('button', { name: '获取模型', exact: true }).click()
    await expect(card.getByRole('alert')).toContainText('非文本模型')
    const blockedRefresh = await page.evaluate(
      async ({ id, meetingId }) => ({
        select: await window.paa.selectModelService(id),
        generate: await window.paa.generateSummary(meetingId),
      }),
      { id: a, meetingId },
    )
    expect(!blockedRefresh.select.ok && blockedRefresh.select.message).toContain('非文本模型')
    expect(!blockedRefresh.generate.ok && blockedRefresh.generate.code).toBe('nontext_model')
    expect(calls.filter((call) => (call.body?.messages as unknown[])?.length === 2)).toHaveLength(0)
    futureIsText = true
    await card.getByRole('button', { name: '获取模型', exact: true }).click()
    await expect(card.getByRole('option', { name: 'future-kimi', exact: true })).toHaveJSProperty(
      'disabled',
      false,
    )
    await expect(card.getByRole('alert')).toHaveCount(0)
    const b: ServiceDraft = {
      id: randomUUID(),
      name: '服务乙',
      baseUrl,
      apiKey: 'fake-second-key',
      model: 'new-minimax',
      models: [],
      stream: false,
    }
    expect(
      (
        await page.evaluate(
          (serialized) => window.paa.saveModelService(JSON.parse(serialized)),
          JSON.stringify(b),
        )
      ).ok,
    ).toBe(true)
    expect(
      JSON.stringify(await page.evaluate((id) => window.paa.getModelService(id), a)),
    ).not.toContain('fake-only-smoke-key')
    expect(readFileSync(join(root, 'model-services.json'), 'utf8')).not.toContain(
      'fake-only-smoke-key',
    )
    await page.getByRole('button', { name: '会议记录', exact: true }).click()
    await page.locator('.meeting-row').first().click()
    const minutes = page.getByLabel('会议纪要', { exact: true })
    await minutes.getByRole('button', { name: '生成纪要', exact: true }).click()
    await expect(minutes.getByText('纪要已完成', { exact: true })).toBeVisible()
    await expect(minutes).toContainText('负责人：待确认')
    const summaryCall = calls.find((call) => (call.body?.messages as unknown[])?.length === 2)
    expect(summaryCall?.body?.thinking).toEqual({ enabled: true, budget: 2048 })
    expect(summaryCall?.key).toBe('Bearer fake-only-smoke-key')
    const messages = summaryCall?.body?.messages as { content: string }[]
    expect(JSON.parse(messages[1].content).segments).toHaveLength(61)
    await minutes.getByRole('button', { name: '原文 1', exact: true }).first().click()
    await expect(page.getByLabel('纪要引用原文')).toContainText('最后决定取消上线')
    await page.getByRole('button', { name: '播放此处录音', exact: true }).click()
    await expect
      .poll(() =>
        page.locator('audio').evaluate((audio) => (audio as HTMLAudioElement).currentTime),
      )
      .toBeGreaterThan(59)
    const saved = await page.evaluate((id) => window.paa.getSummary(id), meetingId)
    fail = true
    await minutes.getByRole('button', { name: '重新生成纪要', exact: true }).click()
    await expect(minutes.getByText('生成失败', { exact: true })).toBeVisible()
    await expect(minutes).toContainText('以下为上一次成功保存的纪要')
    await expect(minutes.getByRole('heading', { name: '上线安排', exact: true })).toBeVisible()
    await close(app)
    app = await launch()
    page = await app.firstWindow()
    await expect
      .poll(async () => (await page.evaluate(() => window.paa.getStatus())).connection)
      .toBe('ready')
    const restored = await page.evaluate((id) => window.paa.getSummary(id), meetingId)
    expect(restored.ok && restored.value.result).toEqual(saved.ok && saved.value.result)
    const services = await page.evaluate(() => window.paa.listModelServices())
    expect(services.ok && services.value.activeProfileId).toBe(a)
    expect(calls.filter((call) => (call.body?.messages as unknown[])?.length === 2)).toHaveLength(2)
    await page.getByRole('button', { name: '设置', exact: true }).click()
    await page.getByRole('button', { name: '服务甲 · 使用中', exact: true }).click()
    await page.getByLabel('API Base URL', { exact: true }).fill(baseUrl + '/changed')
    await page.getByRole('button', { name: '获取模型', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('密钥')
    await page.getByRole('button', { name: '服务甲 · 使用中', exact: true }).click()
    modelDelay = 300
    await page.getByRole('button', { name: '获取模型', exact: true }).click()
    await page.getByLabel('API Base URL', { exact: true }).fill('https://new.example.com/v1')
    await expect(page.getByLabel('可用模型列表')).toHaveCount(0)
    await new Promise((resolve) => setTimeout(resolve, 700))
    await expect(page.getByLabel('可用模型列表')).toHaveCount(0)
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(900, 640))
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true)
  } finally {
    if (app.process().exitCode === null) await close(app)
    await new Promise<void>((resolve) => server.close(() => resolve()))
    rmSync(root, { recursive: true, force: true })
  }
})
