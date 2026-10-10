import { test, expect } from '../fixtures/test'

test.use({ reducedMotion: 'no-preference', video: 'on' })

declare global {
  interface Window {
    acceptanceSources: (EventTarget & { closed: boolean; close: () => void })[]
  }
}

for (const { width, cancel } of [
  { width: 1440, cancel: false },
  { width: 390, cancel: false },
  { width: 390, cancel: true },
]) {
  const title = cancel
    ? 'W24 @cross controlled cancellation: click stop, retain prose and reject late events'
    : `W24 @cross controlled streaming ${width}: smooth Markdown, stable controls, scroll and final handoff`
  test(title, async ({ page, state, login, capture }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 })
    await page.addInitScript(() => {
      window.acceptanceSources = []
      class ControlledSource extends EventTarget {
        closed = false
        constructor() {
          super()
          window.acceptanceSources.push(this)
        }
        close() {
          this.closed = true
        }
      }
      window.EventSource = ControlledSource as unknown as typeof EventSource
    })
    await login('employee')
    const node = {
      id: 'read',
      parentId: null,
      kind: 'tool',
      label: '读取合成资料',
      state: 'succeeded',
      attempts: 1,
      maxAttempts: 4,
      retries: 0,
      totalRetries: 0,
      round: 0,
      nextRetryAt: null,
      error: '',
      errorCode: '',
      canRetry: false,
      presentation: { type: 'operation' },
    }
    let job = {
      id: 'controlled-stream-job',
      kind: 'message',
      targetId: 'controlled-stream-message',
      state: 'running',
      phase: 'assistant',
      attempt: 1,
      fence: 2,
      error: '',
      updatedAt: new Date().toISOString(),
      nodes: [node],
    }
    let message = {
      id: job.targetId,
      ownerId: state.users.employee.id,
      conversationId: 'controlled-stream-chat',
      text: '显示长 Markdown 合成内容',
      reply: '',
      replyTo: null,
      transcript: '',
      transcriptRevision: 0,
      createdAt: job.updatedAt,
      attachments: [],
      drafts: [],
      suggestions: [],
      job,
    }
    const conversation = {
      id: message.conversationId,
      title: '受控流式交互',
      revision: 1,
      personaId: 'professional',
    }
    const reads: string[] = []
    const cancellations: unknown[] = []
    await page.route('**/api/v1/**', async (route) => {
      const url = new URL(route.request().url())
      const path = url.pathname.replace('/api/v1', '')
      let data: unknown
      if (path === '/conversations/' + conversation.id) data = conversation
      else if (path === `/conversations/${conversation.id}/active-job`)
        data = { job: ['queued', 'running'].includes(job.state) ? job : null }
      else if (path === `/conversations/${conversation.id}/context-usage`)
        data = { contextUsage: null }
      else if (path === `/conversations/${conversation.id}/interactions`) data = { items: [] }
      else if (path === '/messages' && url.searchParams.get('conversationId') === conversation.id)
        data = { items: [message], nextCursor: null }
      else if (path === `/messages/${message.id}`) data = message
      else if (path === `/jobs/${job.id}`) data = job
      else if (path === `/jobs/${job.id}/cancel` && route.request().method() === 'POST') {
        cancellations.push(route.request().postDataJSON())
        job = { ...job, state: 'cancelled', fence: 3 }
        const replyStream = {
          version: 1,
          generation: 1,
          state: 'interrupted',
          text: '可保留的中断片段',
        }
        const cancelled = { ...message, job, replyStream }
        message = cancelled
        data = { ...job, replyStream }
      } else if (
        path === '/business-actions' &&
        url.searchParams.get('conversationId') === conversation.id
      )
        data = { items: [] }
      else return route.continue()
      reads.push(path)
      await route.fulfill({ json: data })
    })
    await page.goto(state.origin + '/assistant/' + conversation.id)
    const input = page.getByRole('textbox', { name: '工作消息' })
    const stop = page.getByRole('button', { name: '中断', exact: true })
    await expect(stop).toBeVisible()
    await expect(page.getByRole('alert')).toHaveCount(0)
    await expect
      .poll(() => page.evaluate(() => window.acceptanceSources.filter((s) => !s.closed).length))
      .toBe(1)
    const inputNode = await input.elementHandle()
    const stopNode = await stop.elementHandle()
    const details = page.locator('[data-chat-content] details').first()
    await details.locator('summary').click()
    let seq = 0
    async function emit(text: string, streamState = 'streaming', state = 'running') {
      const value = {
        jobId: job.id,
        attempt: 1,
        fence: 2,
        seq: ++seq,
        state,
        stage: 'generating',
        text: '',
        error: '',
        updatedAt: new Date().toISOString(),
        nodes: [node],
        replyStream: { version: 1, generation: 1, state: streamState, text },
      }
      await page.evaluate(
        (value) =>
          window.acceptanceSources
            .filter((s) => !s.closed)
            .forEach((source) =>
              source.dispatchEvent(new MessageEvent('snapshot', { data: JSON.stringify(value) })),
            ),
        value,
      )
      // Match server coalescing; normal-motion rendering is captured in the video.
      await page.waitForTimeout(220)
    }
    if (cancel) {
      await emit('可保留的中断片段')
      await expect(page.getByText('可保留的中断片段', { exact: true })).toBeVisible()
      await stop.click()
      await expect(stop).toHaveCount(0)
      await expect(page.getByText(/^已中断 · 已完成 1 项操作$/)).toBeVisible()
      await expect(page.getByText('可保留的中断片段', { exact: true })).toHaveCount(1)
      expect(cancellations).toEqual([{ expectedAttempt: 1, expectedFence: 2 }])
      expect(await inputNode!.evaluate((node) => node.isConnected)).toBe(true)
      await page.evaluate(() => {
        for (const source of window.acceptanceSources)
          source.dispatchEvent(
            new MessageEvent('snapshot', {
              data: JSON.stringify({
                jobId: 'controlled-stream-job',
                attempt: 1,
                fence: 2,
                seq: 99,
                state: 'running',
                stage: 'generating',
                nodes: [],
                replyStream: {
                  version: 1,
                  generation: 1,
                  state: 'streaming',
                  text: '迟到正文不可显示',
                },
              }),
            }),
          )
      })
      await expect(page.getByText('迟到正文不可显示', { exact: true })).toHaveCount(0)
      await expect(page.getByRole('button', { name: '发送', exact: true })).toBeVisible()
      await expect(page.getByRole('alert')).toHaveCount(0)
      await capture('controlled-cancelled')
      return
    }
    let text =
      '# 受控流式预览\n\n第一段正在生成。\n\n|阶段|结果|\n|---|---|\n|读取|完成|\n\n```js\nconsole.log("' +
      'x'.repeat(220) +
      '")\n```\n\n'
    const before = reads.length
    for (let n = 1; n <= 10; n++) {
      text += `## 建议 ${n}\n\n继续补充可读的说明。保持阅读位置、输入框与中断按钮稳定。\n\n`
      await emit(text)
    }
    expect(reads.length).toBe(before)
    expect(await inputNode!.evaluate((node) => node.isConnected)).toBe(true)
    expect(await stopNode!.evaluate((node) => node.isConnected)).toBe(true)
    expect(await details.evaluate((node) => (node as HTMLDetailsElement).open)).toBe(true)
    const scroller = page.locator('[data-chat-content]').locator('..')
    await expect
      .poll(() =>
        scroller.evaluate((node) => node.scrollHeight - node.scrollTop - node.clientHeight),
      )
      .toBeLessThan(8)
    await scroller.evaluate((node) => {
      node.scrollTop = 0
      node.dispatchEvent(new Event('scroll'))
    })
    await emit(text + '\n用户向上阅读时的新段落。')
    expect(await scroller.evaluate((node) => node.scrollTop)).toBeLessThan(8)
    await capture(`streaming-${width}`)
    const intermediate: number[] = await page
      .locator('[data-reply-state="streaming"]')
      .evaluate(async (node) => {
        const lengths = []
        for (let i = 0; i < 8; i++) {
          await new Promise(requestAnimationFrame)
          lengths.push(node.textContent?.length ?? 0)
        }
        return lengths
      })
    expect(intermediate.every((length) => length > 0)).toBe(true)
    job = { ...job, state: 'succeeded' }
    message = { ...message, reply: text, job }
    await emit(text, 'finalizing', 'succeeded')
    await expect(page.getByRole('button', { name: '发送', exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { name: '受控流式预览', exact: true })).toHaveCount(1)
    await expect(page.locator('[data-reply-state="streaming"]')).toHaveCount(0)
    await capture(`stream-final-${width}`)
  })
}

test('W19 normal-motion login book and pet remain visible during keyboard navigation', async ({
  page,
  state,
  login,
  capture,
}) => {
  await page.goto(state.origin)
  const cover = page.getByRole('button', { name: '打开书本，进入登录页' })
  await cover.focus()
  await page.keyboard.press('Enter')
  const book = page.locator('[data-state="opening"]')
  await expect(book).toBeVisible()
  await expect(page.locator('[data-state="open"]')).toBeVisible()
  await expect(page.getByLabel('账号', { exact: true })).toBeFocused()
  await capture('normal-motion-book-open')
  await page.keyboard.press('Escape')
  await expect(page.locator('[data-state="closed"]')).toBeVisible()
  await expect(page.getByRole('button', { name: /翻开，和 Noria 一起出发/ })).toBeFocused()
  await login('employee')
  const pet = page.getByRole('button', { name: 'Noria 外观', exact: true })
  await expect(pet).toBeVisible()
  const node = await pet.elementHandle()
  await pet.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog', { name: 'Noria 外观' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(pet).toBeFocused()
  await page.getByRole('link', { name: '我的工作', exact: true }).click()
  await expect(page.getByRole('heading', { name: '我的工作', exact: true })).toBeVisible()
  expect(await node!.evaluate((node) => node.isConnected)).toBe(true)
  await capture('normal-motion-pet-stable')
})
