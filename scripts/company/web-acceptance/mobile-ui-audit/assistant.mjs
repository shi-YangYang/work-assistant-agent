import { writeFile, readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import {
  launch,
  screenshot,
  output,
  origin,
  message,
  job,
  attachment,
  wav,
  png,
  previewPng,
  expect,
} from './assistant-fixture.mjs'

const index = JSON.parse(
  await readFile(resolve(output, 'screenshot-index.json'), 'utf8').catch(() => '[]'),
)
const results = []
async function capture(run, id, name, notes) {
  return screenshot(run, index, id, name, notes)
}
async function closeModal(page) {
  await page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).click()
}
async function group(id, options, fn) {
  let run
  try {
    run = await launch(options)
    await fn(run)
    results.push({
      id,
      ...run.env,
      status: run.s.errors.length || run.s.unhandled.length ? 'HARNESS_REVIEW' : 'PASS',
      unhandled: run.s.unhandled,
      pageErrors: run.s.errors,
    })
  } catch (error) {
    results.push({ id, ...run?.env, status: 'BLOCKED', error: String(error) })
    if (run) await capture(run, id, 'first-failure', String(error))
  } finally {
    if (run) {
      await writeFile(resolve(output, id + '-requests.json'), JSON.stringify(run.s.log, null, 2))
      await run.close()
    }
    await writeFile(
      resolve(output, 'results-' + (process.env.AUDIT_GROUP || 'base') + '.json'),
      JSON.stringify(results, null, 2),
    )
  }
}
async function goto(run, path = '/assistant/audit-chat') {
  await run.page.goto(origin + path)
  await run.page.getByRole('textbox', { name: '工作消息' }).waitFor()
  await run.page.waitForTimeout(200)
}
async function panel(page) {
  const b = page.getByRole('button', { name: '更多功能', exact: true })
  await b.click()
}

const which = process.env.AUDIT_GROUP || 'base'
if (which === 'base')
  for (const theme of ['light', 'dark'])
    await group('M03-M04-' + theme, { theme }, async (run) => {
      const { page } = run
      await goto(run, '/assistant?new=1')
      await capture(run, 'M03', 'new-empty')
      await page.getByRole('button', { name: /选择人设/ }).click()
      await capture(run, 'M03', 'persona-menu')
      await page.getByRole('menuitemradio', { name: /专业人设/ }).click()
      await page.getByRole('button', { name: '会话列表', exact: true }).click()
      await capture(run, 'M03', 'conversation-list')
      await page.getByRole('textbox', { name: '搜索会话' }).fill('不存在的内容')
      await expect(page.getByText('没有匹配的会话')).toBeVisible()
      await capture(run, 'M03', 'no-search')
      await page.getByRole('textbox', { name: '搜索会话' }).fill('')
      await page
        .getByRole('button', { name: /^重命名会话：/ })
        .first()
        .click()
      await capture(run, 'M03', 'rename')
      await page.getByLabel('会话名称').fill('审计重命名会话')
      await page.getByRole('button', { name: '保存', exact: true }).click()
      await expect(page.getByRole('dialog', { name: '重命名会话' })).toHaveCount(0)
      await page.getByRole('button', { name: '会话列表', exact: true }).click()
      await page.getByRole('link', { name: '审计重命名会话', exact: true }).click()
      await page.waitForURL('**/assistant/audit-chat')
      await page.waitForTimeout(200)
      const draft =
        '先分析附件中的实际内容。\n保留原文，分别整理关键风险和下一步。\n长草稿的最后一行。'
      await page.getByRole('textbox', { name: '工作消息' }).fill(draft)
      await panel(page)
      await capture(run, 'M04', 'long-draft-plus')
      await page.getByRole('button', { name: /^上下文使用情况/ }).click()
      await capture(run, 'M04', 'context-modal')
      await closeModal(page)
      await page.getByRole('button', { name: /^思考强度/ }).click()
      await capture(run, 'M04', 'reasoning-modal')
      await page.getByRole('menuitemradio', { name: 'low', exact: true }).click()
      await page.getByRole('button', { name: /^执行权限/ }).click()
      await capture(run, 'M04', 'execution-modal')
      await page.getByRole('menuitemradio', { name: /自动审核/ }).click()
      await expect(page.getByRole('textbox', { name: '工作消息' })).toHaveValue(draft)
      await page.getByRole('button', { name: '发送', exact: true }).click()
      await expect(page.getByText('整理好了。优先核对关键资料，再完成下一步工作。')).toBeVisible()
      await capture(run, 'J02', 'sent-draft')
      await page.reload()
      await expect(page.getByText('整理好了。优先核对关键资料，再完成下一步工作。')).toBeVisible()
      await capture(run, 'M03', 'history-refresh')
      await page.getByRole('button', { name: '会话列表', exact: true }).click()
      await page
        .getByRole('button', { name: /^删除会话：/ })
        .first()
        .click()
      await capture(run, 'M03', 'delete-dialog')
      await page.getByRole('button', { name: '确认删除', exact: true }).click()
      await expect(page.getByRole('dialog', { name: '删除会话' })).toHaveCount(0)
      await capture(run, 'M03', 'after-delete')
    })
if (which === 'boundaries')
  for (const opts of [
    { width: 320, height: 568 },
    { width: 360, height: 800 },
    { width: 430, height: 932 },
    { width: 390, height: 480 },
    { width: 844, height: 390 },
    { width: 390, height: 844, theme: 'dark', browserName: 'webkit' },
    { width: 390, height: 844, role: 'admin' },
    { width: 390, height: 844, pet: true },
    { width: 320, height: 568, theme: 'dark', motion: 'reduce' },
  ])
    await group('S02-S07-' + JSON.stringify(opts).replace(/[^a-z0-9]/gi, ''), opts, async (run) => {
      const { page, s } = run
      s.messages = [
        message({
          text: '极长中文消息'.repeat(16),
          reply:
            '# 结果\n\n' +
            ('这是一段正文说明，包含很长的无空格英文：' + 'UnbrokenLongText'.repeat(12)) +
            '\n\n|资料|结果|说明|\n|---|---|---|\n|文件甲|通过|' +
            '长表格字段'.repeat(12) +
            '|\n\n```python\n' +
            'print("very_long_code") '.repeat(18) +
            '\n```\n\n1. 完成核对\n2. 执行后续工作。',
        }),
      ]
      await goto(run)
      await capture(run, 'M06', 'long-markdown')
      await panel(page)
      await capture(run, 'M04', 'plus-boundary')
      await page.getByRole('button', { name: /^上下文使用情况/ }).click()
      await capture(run, 'M04', 'context-boundary')
      await closeModal(page)
      await page.getByRole('button', { name: /^执行权限/ }).click()
      await capture(run, 'M04', 'execution-boundary')
      await closeModal(page)
      await page.getByRole('button', { name: '会话列表', exact: true }).click()
      await capture(run, 'M03', 'history-boundary')
    })
if (which === 'voice')
  await group('J04-voice', { record: true }, async (run) => {
    const { page, s } = run
    await goto(run)
    const draft = '这段文字必须保留，不随长按语音发送'
    await page.getByRole('textbox', { name: '工作消息' }).fill(draft)
    await page.getByRole('button', { name: '切换到语音输入' }).click()
    await capture(run, 'J04', 'voice-idle')
    const button = page.getByRole('button', { name: '点击录音，长按发送', exact: true })
    let box = await button.boundingBox()
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.down()
    await page.waitForTimeout(1100)
    await capture(run, 'J04', 'holding-1')
    await page.waitForTimeout(300)
    await capture(run, 'J04', 'holding-2')
    await page.mouse.move(box.x + box.width / 2, box.y - 100, { steps: 8 })
    await capture(run, 'J04', 'cancel-1')
    await page.waitForTimeout(300)
    await capture(run, 'J04', 'cancel-2')
    await page.mouse.up()
    await expect(button).toBeVisible()
    await capture(run, 'J04', 'cancel-released')
    box = await button.boundingBox()
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.down()
    await page.waitForTimeout(1600)
    await page.mouse.up()
    await expect.poll(() => s.lastSend).toBeTruthy()
    expect(s.lastSend.text).toBe('')
    expect(s.lastSend.attachmentIds.length).toBe(1)
    await capture(run, 'J04', 'direct-sent')
    await page.getByRole('button', { name: '切换到文字输入' }).click()
    await expect(page.getByRole('textbox', { name: '工作消息' })).toHaveValue(draft)
    await capture(run, 'J04', 'draft-preserved')
    s.messages = [
      message({
        text: '两段语音一起整理。',
        transcript: '第一段：先核对材料。\n第二段：整理工作计划。',
        transcriptRevision: 1,
        attachments: [
          attachment('audio', 'audio-one', '第一段.wav'),
          attachment('audio', 'audio-two', '第二段.wav'),
        ],
      }),
    ]
    await page.reload()
    await page.getByRole('button', { name: '转文字', exact: true }).click()
    await capture(run, 'M05', 'multi-audio-transcript')
    await page.getByRole('button', { name: '改文字', exact: true }).click()
    await capture(run, 'M05', 'transcript-edit')
    await page.getByRole('textbox', { name: '语音文字' }).fill('修正后的转写内容。')
    await page.getByRole('button', { name: '保存修正' }).click()
    await expect(page.getByText('修正后的转写内容。')).toBeVisible()
    await capture(run, 'J04', 'corrected-transcript')
  })
if (which === 'uploads')
  for (const theme of ['light', 'dark'])
    await group('J03-upload-' + theme, { theme, record: true }, async (run) => {
      const { page, s } = run
      await goto(run)
      s.uploadDelay = 1400
      s.uploadFailures = 1
      await page
        .locator('input[type=file]')
        .last()
        .setInputFiles([
          {
            name: '季度工作计划_这是一份很长的文件名_应显示省略号.md',
            mimeType: 'text/markdown',
            buffer: Buffer.from('# 示例合成资料\n只用于UI测试'),
          },
          { name: 'photo.png', mimeType: 'image/png', buffer: png },
          { name: 'audio-note.wav', mimeType: 'audio/wav', buffer: wav() },
        ])
      await expect(page.getByRole('region', { name: /待发送附件/ })).toBeVisible()
      await capture(run, 'M05', 'mixed-uploading')
      await page.waitForTimeout(2000)
      await capture(run, 'M05', 'mixed-failed')
      await page.getByRole('button', { name: /重试上传/ }).click()
      await page.waitForTimeout(1600)
      await capture(run, 'M05', 'mixed-ready')
      await page
        .locator('input[type=file]')
        .last()
        .setInputFiles([
          { name: '同名附件.md', mimeType: 'text/markdown', buffer: Buffer.from('第一份') },
          { name: '同名附件.md', mimeType: 'text/markdown', buffer: Buffer.from('第二份') },
        ])
      await page.waitForTimeout(1700)
      await capture(run, 'M05', 'duplicate-names')
      await page
        .getByRole('region', { name: /待发送附件/ })
        .evaluate((e) => (e.scrollLeft = e.scrollWidth))
      await capture(run, 'M05', 'attachments-scrolled')
      const remove = page.getByRole('button', { name: /移除同名附件/ }).last()
      await expect(remove).toBeVisible()
      await remove.click()
      await capture(run, 'M05', 'removed-attachment')
      await page.getByRole('textbox', { name: '工作消息' }).fill('分析混合附件。')
      await page.getByRole('button', { name: '发送', exact: true }).click()
      await expect(page.getByText('整理好了。优先核对关键资料，再完成下一步工作。')).toBeVisible()
      await capture(run, 'J03', 'mixed-sent')
      await page.reload()
      await expect(page.getByText('分析混合附件。')).toBeVisible()
      await capture(run, 'J03', 'mixed-refresh')
    })
if (which === 'images')
  for (const theme of ['light', 'dark'])
    await group('J06-images-' + theme, { theme, record: true }, async (run) => {
      const { page, s } = run
      for (const stage of ['generating', 'cancelled', 'failed', 'ready']) {
        const slots = [0, 1, 2, 3].map((n) => ({
          operation: n + 1,
          state: stage === 'generating' ? (n === 0 ? 'generating' : 'queued') : stage,
          ...(stage === 'ready' ? { deliverableId: 'images', revision: 1 } : {}),
          width: 2048,
          height: 2048,
        }))
        const files = [0, 1, 2, 3].map((n) => ({
          id: 'image-' + n,
          name: `image-${n}.png`,
          mimeType: 'image/png',
          size: png.length,
          width: 800,
          height: 800,
          url: '/api/v1/deliverables/images/files/image-' + n + '?revision=1',
        }))
        s.messages = [
          message({
            text: '生成四张合成图片。',
            reply: stage === 'ready' ? '四张图片已生成。' : '',
            job: job({
              state: stage === 'generating' ? 'running' : stage === 'ready' ? 'succeeded' : stage,
              stage: stage === 'generating' ? 'executing' : 'complete',
              imageGeneration: slots,
              nodes: [
                {
                  id: 'image',
                  kind: 'tool',
                  label: '生成图片',
                  state: stage === 'generating' ? 'running' : 'succeeded',
                  presentation: { type: 'operation' },
                },
              ],
            }),
            deliverables:
              stage === 'ready'
                ? [
                    {
                      id: 'images',
                      revision: 1,
                      latestRevision: 1,
                      title: '合成图片（4张）',
                      messageId: 'audit-message',
                      itemCount: 4,
                      updatedAt: '2026-10-17T01:00:00Z',
                      files,
                    },
                  ]
                : [],
          }),
        ]
        await goto(run)
        await page.getByRole('list', { name: '生成图片' }).waitFor()
        await capture(run, 'M06', 'images-' + stage)
        if (stage === 'generating') {
          await page.waitForTimeout(350)
          await capture(run, 'M06', 'images-generating-motion')
        }
        if (stage === 'ready') {
          await page.getByRole('list', { name: '生成图片' }).getByRole('button').first().click()
          await capture(run, 'J06', 'image-preview')
          await page.keyboard.press('Escape')
          await capture(run, 'J06', 'image-preview-closed')
        }
      }
    })
if (which === 'stream')
  await group('J05-stream', { record: true, pet: true }, async (run) => {
    const { page, s } = run
    s.messages = [
      message({ reply: '', job: job({ state: 'running', stage: 'thinking', phase: 'assistant' }) }),
    ]
    await goto(run)
    await page.waitForTimeout(1200)
    await capture(run, 'J05', 'thinking')
    let text = '## 合成流式回复\n\n'
    for (let n = 1; n <= 5; n++) {
      text += `第 ${n} 段内容逐步显示，正在整理长材料。\n\n`
      await page.evaluate(
        ({ text, n }) =>
          window.auditSources
            .filter((s) => !s.closed && s.url.includes('/jobs/'))
            .forEach((source) =>
              source.dispatchEvent(
                new MessageEvent('snapshot', {
                  data: JSON.stringify({
                    jobId: 'audit-job',
                    attempt: 1,
                    fence: 1,
                    seq: n,
                    state: 'running',
                    stage: 'generating',
                    text: '',
                    error: '',
                    updatedAt: new Date().toISOString(),
                    replyStream: { version: 1, generation: 1, state: 'streaming', text },
                  }),
                }),
              ),
            ),
        { text, n },
      )
      await page.waitForTimeout(250)
      await capture(run, 'J05', 'stream-' + n)
    }
    s.messages = [message({ reply: text, job: job() })]
    await page.goto(origin + '/work')
    await page.getByRole('heading', { name: '我的工作', exact: true }).waitFor()
    await page.goto(origin + '/assistant/audit-chat')
    await page.getByRole('heading', { name: '合成流式回复' }).waitFor()
    await capture(run, 'J05', 'returned-complete')
    await panel(page)
    await page.getByRole('button', { name: /^上下文使用情况/ }).click()
    await capture(run, 'J05', 'context-after-complete')
  })
if (which === 'supplement') {
  await group('M03-stable-dialogs', {}, async (run) => {
    const { page } = run
    await goto(run)
    await page.getByRole('button', { name: '会话列表', exact: true }).click()
    await expect(page.getByRole('button', { name: /^重命名会话：/ })).toHaveCount(8)
    await capture(run, 'M03', 'conversation-loaded')
    await page
      .getByRole('button', { name: /^删除会话：/ })
      .first()
      .click()
    await page.getByRole('dialog', { name: '删除会话' }).waitFor()
    await capture(run, 'M03', 'delete-confirm-loaded')
    await page.getByRole('button', { name: '取消', exact: true }).click()
    await capture(run, 'M03', 'delete-cancelled')
    await panel(page)
    await page.getByRole('button', { name: '引用工作', exact: true }).click()
    await page.getByRole('dialog').waitFor()
    await capture(run, 'M04', 'reference-work-empty')
  })
  await group('S05-landscape', { width: 844, height: 390 }, async (run) => {
    const { page } = run
    await goto(run)
    await page.getByRole('textbox', { name: '工作消息' }).fill('横屏长草稿\n第二行\n第三行\n第四行')
    await capture(run, 'M04', 'landscape-draft')
    await page.getByRole('button', { name: /^上下文使用情况/ }).click()
    await capture(run, 'M04', 'landscape-context')
    await page.getByRole('button', { name: '关闭上下文详情' }).click()
    await page.getByRole('button', { name: /^执行权限/ }).click()
    await capture(run, 'M04', 'landscape-execution')
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: /^思考强度/ }).click()
    await capture(run, 'M04', 'landscape-reasoning')
  })
  await group('S07-text200', {}, async (run) => {
    const { page, s } = run
    s.messages = [
      message({
        reply:
          '## 检查结果\n\n这是一段需要在字体放大时仍然可以阅读的回复。\n\n- 合理换行\n- 操作按钮不能被遮住。',
      }),
    ]
    await goto(run)
    await page
      .getByRole('textbox', { name: '工作消息' })
      .fill('我希望整理全部材料，并保留原文中的重要细节。')
    await panel(page)
    await page.evaluate(() => {
      for (const e of document.querySelectorAll('body *')) {
        const cs = getComputedStyle(e)
        if (cs.fontSize && e instanceof HTMLElement) {
          e.dataset.auditOriginalFont = cs.fontSize
        }
      }
      for (const e of document.querySelectorAll('[data-audit-original-font]'))
        e.style.fontSize = parseFloat(e.dataset.auditOriginalFont) * 2 + 'px'
    })
    await capture(
      run,
      'S07',
      'text200-composer',
      '以页面当前计算字体乘2进行浏览器仿真，不等同真机系统字体。',
    )
    await page.getByRole('button', { name: /^上下文使用情况/ }).click()
    await page.evaluate(() => {
      for (const e of document.querySelectorAll('[role=dialog] *'))
        if (e instanceof HTMLElement)
          e.style.fontSize = parseFloat(getComputedStyle(e).fontSize) * 2 + 'px'
    })
    await capture(run, 'S07', 'text200-context')
  })
  for (const theme of ['light', 'dark'])
    await group('M05-audio-' + theme, { theme, record: true }, async (run) => {
      const { page, s } = run
      s.messages = [
        message({
          text: '两段语音一起整理。',
          transcript: '第一段：先核对材料。\n第二段：整理工作计划。',
          transcriptRevision: 1,
          attachments: [
            attachment('audio', 'audio-one', '第一段.wav'),
            attachment('audio', 'audio-two', '第二段.wav'),
          ],
        }),
      ]
      await goto(run)
      await page.getByRole('button', { name: '播放语音 1' }).click()
      await page.waitForTimeout(250)
      await capture(run, 'M05', 'multi-audio-playing-1')
      await page.waitForTimeout(350)
      await capture(run, 'M05', 'multi-audio-playing-2')
      await page.getByRole('button', { name: '转文字', exact: true }).click()
      await capture(run, 'M05', 'multi-audio-transcript')
      await page.getByRole('button', { name: '改文字', exact: true }).click()
      await page.getByRole('dialog', { name: '修正语音文字' }).waitFor()
      await capture(run, 'M05', 'transcript-edit')
      await page.getByRole('textbox', { name: '语音文字' }).fill('修正后的转写内容。')
      await page.getByRole('button', { name: '保存修正' }).click()
      await expect(page.getByText('修正后的转写内容。')).toBeVisible()
      await capture(run, 'M05', 'transcript-saved')
    })
  await group('J04-voice-click-failed', { record: true }, async (run) => {
    const { page, s } = run
    await goto(run)
    const draft = '保留这段草稿'
    await page.getByRole('textbox', { name: '工作消息' }).fill(draft)
    await page.getByRole('button', { name: '切换到语音输入' }).click()
    await page.getByRole('button', { name: '点击录音，长按发送', exact: true }).click()
    await page.waitForTimeout(1500)
    await capture(run, 'J04', 'click-recording')
    await page.getByRole('button', { name: /停止录音/ }).click()
    await expect(page.getByRole('region', { name: /待发送附件/ })).toBeVisible()
    await capture(run, 'J04', 'click-recording-draft')
    await page.getByRole('button', { name: /移除语音/ }).click()
    s.failSend = true
    const b = page.getByRole('button', { name: '点击录音，长按发送', exact: true })
    const rect = await b.boundingBox()
    await page.mouse.move(rect.x + rect.width / 2, rect.y + rect.height / 2)
    await page.mouse.down()
    await page.waitForTimeout(1400)
    await page.mouse.up()
    await page.waitForTimeout(800)
    await capture(run, 'J04', 'direct-send-failure')
    await page.getByRole('button', { name: '切换到文字输入' }).click()
    await expect(page.getByRole('textbox', { name: '工作消息' })).toHaveValue(draft)
    await capture(run, 'J04', 'failure-draft-preserved')
  })
  await group('M06-images-ready-valid', { record: true }, async (run) => {
    const { page, s } = run
    const files = [0, 1, 2, 3].map((n) => ({
      id: 'image-' + n,
      name: `image-${n}.png`,
      mimeType: 'image/png',
      size: png.length,
      width: 800,
      height: 800,
      url: '/api/v1/deliverables/images/files/image-' + n + '?revision=1',
    }))
    s.imageDelay = 1500
    s.messages = [
      message({
        reply: '四张图片已生成。',
        deliverables: [
          {
            id: 'images',
            revision: 1,
            latestRevision: 1,
            title: '合成图片（4张）',
            messageId: 'audit-message',
            itemCount: 4,
            updatedAt: '2026-10-17T01:00:00Z',
            files,
          },
        ],
      }),
    ]
    await goto(run)
    await capture(run, 'J06', 'completed-image-loading')
    await page.getByRole('list', { name: '生成图片' }).getByRole('button').first().waitFor()
    await capture(run, 'J06', 'completed-images-loaded')
    await page.getByRole('list', { name: '生成图片' }).getByRole('button').first().click()
    await page.getByRole('dialog').waitFor()
    await capture(run, 'J06', 'image-preview-valid')
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await capture(run, 'J06', 'image-preview-dismissed')
  })
}
if (which === 'final-boundaries') {
  await group('S07-text200-lineheight', {}, async (run) => {
    const { page, s } = run
    s.messages = [
      message({
        reply:
          '## 检查结果\n\n这是一段需要在字体放大时仍然可以阅读的回复。\n\n- 合理换行\n- 操作按钮不能被遮住。',
      }),
    ]
    await goto(run)
    await page
      .getByRole('textbox', { name: '工作消息' })
      .fill('我希望整理全部材料，并保留原文中的重要细节。')
    await panel(page)
    await page.evaluate(() => {
      const entries = [...document.querySelectorAll('body *')]
        .filter((e) => e instanceof HTMLElement)
        .map((e) => {
          const cs = getComputedStyle(e)
          return { e, font: parseFloat(cs.fontSize), line: parseFloat(cs.lineHeight) }
        })
      for (const { e, font, line } of entries) {
        e.style.fontSize = font * 2 + 'px'
        if (Number.isFinite(line)) e.style.lineHeight = line * 2 + 'px'
      }
    })
    await capture(
      run,
      'S07',
      'text200-with-lineheight',
      '当前computed font-size与数值line-height同步×2；非真机系统字体。',
    )
  })
  await group('M06-approval-question', { width: 320, height: 568 }, async (run) => {
    const { page, s } = run
    s.messages = [
      message({
        reply: '请确认下面的更新。',
        actions: [
          {
            id: 'approval',
            messageId: 'audit-message',
            action: 'update_work',
            label: '更新工作',
            title: '很长的工作标题'.repeat(5),
            state: 'pending',
            revision: 1,
            createdAt: '2026-10-17T01:00:00Z',
            canConfirm: true,
            preview: { title: '更新工作', changes: { summary: '需要保留的长摘要'.repeat(20) } },
          },
        ],
      }),
    ]
    await goto(run)
    await page.getByRole('button', { name: '确认执行' }).scrollIntoViewIfNeeded()
    await capture(run, 'M06', 'approval-pending')
    await page.getByRole('button', { name: '确认执行' }).click()
    await expect(page.getByRole('button', { name: '确认执行' })).toHaveCount(0)
    await capture(run, 'M06', 'approval-complete')
    s.interactions = [
      {
        id: 'question',
        messageId: 'audit-message',
        conversationId: 'audit-chat',
        taskId: 'audit-job',
        revision: 1,
        state: 'waiting',
        questions: [
          {
            id: 'q1',
            prompt: '需要整理哪些资料？',
            type: 'single',
            options: [
              {
                id: 'all',
                label: '整理全部文件并合并重复项目',
                description: '包括本次上传和之前会话中已提供的材料。',
              },
              { id: 'recent', label: '只整理本次上传的文件' },
            ],
            allowCustom: true,
          },
        ],
        answers: [],
        createdAt: '2026-10-17T01:00:00Z',
      },
    ]
    await page.reload()
    await page.getByRole('region', { name: '回答助手问题' }).waitFor()
    await capture(run, 'M06', 'question-expanded')
    await page.getByRole('button', { name: '提交回答' }).click()
    await capture(run, 'M06', 'question-validation')
    await page.getByRole('radio').first().check()
    await page.getByRole('button', { name: '提交回答' }).click()
    await expect(page.getByRole('region', { name: '回答助手问题' })).toHaveCount(0)
    await capture(run, 'M06', 'question-answered')
  })
  await group('J03-multiple-batches', {}, async (run) => {
    const { page, s } = run
    await goto(run)
    for (const [batch, count] of [
      [1, 6],
      [2, 5],
    ]) {
      await page
        .locator('input[type=file]')
        .last()
        .setInputFiles(
          Array.from({ length: count }, (_, n) => ({
            name: `批次${batch}-材料${n + 1}.md`,
            mimeType: 'text/markdown',
            buffer: Buffer.from('合成批次材料 ' + batch + ' ' + n),
          })),
        )
      await expect.poll(() => s.uploads.size).toBe(batch === 1 ? 6 : 11)
      await page.getByRole('textbox', { name: '工作消息' }).fill('处理第 ' + batch + ' 批附件')
      await page.getByRole('button', { name: '发送', exact: true }).click()
      await expect.poll(() => s.lastSend?.text).toBe('处理第 ' + batch + ' 批附件')
      await page.getByRole('button', { name: '中断', exact: true }).waitFor({ state: 'hidden' })
      await capture(run, 'J03', 'batch-' + batch + '-sent')
    }
    await page.reload()
    await page.getByRole('textbox', { name: '工作消息' }).fill('请继续处理第一批材料')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await expect.poll(() => s.lastSend?.text).toBe('请继续处理第一批材料')
    await capture(
      run,
      'J03',
      'followup-earlier-batch',
      '仅验证受控UI能连续发送、刷新与追问；不证明模型读取早期材料。',
    )
  })
  await group('J04-success-draft-preserve', {}, async (run) => {
    const { page, s } = run
    await goto(run)
    await page.getByRole('textbox', { name: '工作消息' }).fill('长按语音不会带走这段草稿')
    await page.getByRole('button', { name: '切换到语音输入' }).click()
    const b = page.getByRole('button', { name: '点击录音，长按发送', exact: true })
    const box = await b.boundingBox()
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.down()
    await page.waitForTimeout(1300)
    await page.mouse.up()
    await expect.poll(() => s.lastSend?.text).toBe('')
    await page.getByRole('button', { name: '切换到文字输入' }).click()
    await expect(page.getByRole('textbox', { name: '工作消息' })).toHaveValue(
      '长按语音不会带走这段草稿',
    )
    await capture(run, 'J04', 'success-draft-preserved')
  })
}
if (which === 'recovery') {
  await group('J03-batches-terminal-snapshot', {}, async (run) => {
    const { page, s } = run
    await goto(run)
    for (const [batch, count] of [
      [1, 6],
      [2, 5],
    ]) {
      if (batch === 2) {
        await page.reload()
        await page.getByRole('textbox', { name: '工作消息' }).waitFor()
      }
      await page
        .locator('input[type=file]')
        .last()
        .setInputFiles(
          Array.from({ length: count }, (_, n) => ({
            name: `批次${batch}-材料${n + 1}.md`,
            mimeType: 'text/markdown',
            buffer: Buffer.from('合成批次材料 ' + batch + ' ' + n),
          })),
        )
      await expect.poll(() => s.uploads.size).toBe(batch === 1 ? 6 : 11)
      await page.getByRole('textbox', { name: '工作消息' }).fill('处理第 ' + batch + ' 批附件')
      await page.getByRole('button', { name: '发送', exact: true }).click()
      await expect.poll(() => s.lastSend?.text).toBe('处理第 ' + batch + ' 批附件')
      await expect
        .poll(() =>
          page.evaluate(
            () => window.auditSources.filter((s) => !s.closed && s.url.includes('/jobs/')).length,
          ),
        )
        .toBeGreaterThan(0)
      await page.evaluate(() =>
        window.auditSources
          .filter((s) => !s.closed && s.url.includes('/jobs/'))
          .forEach((source) =>
            source.dispatchEvent(
              new MessageEvent('snapshot', {
                data: JSON.stringify({
                  jobId: 'audit-job',
                  attempt: 1,
                  fence: 1,
                  seq: 20,
                  state: 'succeeded',
                  stage: 'complete',
                  text: '',
                  error: '',
                  updatedAt: new Date().toISOString(),
                }),
              }),
            ),
          ),
      )
      await expect(page.getByRole('button', { name: '中断', exact: true })).toHaveCount(0)
      await capture(
        run,
        'J03',
        'batch-' + batch + '-terminal',
        '两个批次之间刷新；受控终态。实际后端累计材料由环境组验证。',
      )
    }
    await page.reload()
    await page.getByRole('textbox', { name: '工作消息' }).fill('请继续处理第一批材料')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await expect.poll(() => s.lastSend?.text).toBe('请继续处理第一批材料')
    await capture(run, 'J03', 'earlier-batch-followup', '仅验证请求提交，不证明模型读取。')
  })
  await group('J04-success-draft-stable', { record: true }, async (run) => {
    const { page, s } = run
    await goto(run)
    await page.getByRole('textbox', { name: '工作消息' }).fill('长按语音不会带走这段草稿')
    await page.getByRole('button', { name: '切换到语音输入' }).click()
    await page.waitForTimeout(400)
    const b = page.getByRole('button', { name: '点击录音，长按发送', exact: true })
    const box = await b.boundingBox()
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.down()
    await page.waitForTimeout(2600)
    await capture(run, 'J04', 'success-holding-stable')
    await page.mouse.up()
    await expect.poll(() => s.lastSend?.text).toBe('')
    await page.getByRole('button', { name: '切换到文字输入' }).click()
    await expect(page.getByRole('textbox', { name: '工作消息' })).toHaveValue(
      '长按语音不会带走这段草稿',
    )
    await capture(run, 'J04', 'success-draft-preserved-stable')
  })
}
if (which === 'evidence-details') {
  await group('M05-touch-measure', {}, async (run) => {
    const { page, s } = run
    await goto(run)
    await page
      .locator('input[type=file]')
      .last()
      .setInputFiles([
        { name: '触摸目标.md', mimeType: 'text/markdown', buffer: Buffer.from('test') },
        { name: 'voice.wav', mimeType: 'audio/wav', buffer: wav() },
      ])
    await expect.poll(() => s.uploads.size).toBe(2)
    await page.waitForTimeout(200)
    const data = await page.evaluate(() =>
      [...document.querySelectorAll('button')]
        .filter((b) => /移除|播放.*voice/.test(b.getAttribute('aria-label') ?? ''))
        .map((b) => {
          const r = b.getBoundingClientRect()
          const cx = r.x + r.width / 2,
            cy = r.y + r.height / 2
          const hit = (x, y) => {
            const el = document.elementFromPoint(x, y)
            return el === b || b.contains(el)
          }
          let xs = [],
            ys = []
          for (let n = -32; n <= 32; n++) {
            if (hit(cx + n, cy)) xs.push(n)
            if (hit(cx, cy + n)) ys.push(n)
          }
          return {
            name: b.getAttribute('aria-label'),
            rect: r.toJSON(),
            horizontalHitPx: xs.length,
            verticalHitPx: ys.length,
            pseudo: getComputedStyle(b, '::after').inset,
          }
        }),
    )
    await writeFile(
      resolve(output, 'touch-target-measurements.json'),
      JSON.stringify(data, null, 2),
    )
    await capture(run, 'M05', 'touch-target-measure')
  })
  for (const theme of ['light', 'dark'])
    await group('J06-visible-preview-' + theme, { theme }, async (run) => {
      const { page, s } = run
      const files = [0, 1, 2, 3].map((n) => ({
        id: 'preview-' + n,
        name: `合成图片${n + 1}.png`,
        mimeType: 'image/png',
        size: previewPng.length,
        width: 240,
        height: 240,
        url: '/api/v1/deliverables/images/files/preview-' + n + '?revision=1',
      }))
      s.messages = [
        message({
          reply: '四张图片已生成。',
          deliverables: [
            {
              id: 'images',
              revision: 1,
              latestRevision: 1,
              title: '合成图片（4张）',
              messageId: 'audit-message',
              itemCount: 4,
              updatedAt: '2026-10-17T01:00:00Z',
              files,
            },
          ],
        }),
      ]
      await goto(run)
      const list = page.getByRole('list', { name: '生成图片' })
      await expect(list.locator('img')).toHaveCount(4)
      await page.waitForTimeout(300)
      await capture(run, 'J06', 'visible-images-complete')
      await list.getByRole('button').first().click()
      await page.getByRole('dialog').waitFor()
      await expect(page.getByRole('dialog').getByRole('img')).toBeVisible()
      await page.waitForTimeout(300)
      await capture(run, 'J06', 'visible-image-preview')
      await page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).click()
      await expect(page.getByRole('dialog')).toHaveCount(0)
      await capture(run, 'J06', 'visible-preview-closed')
    })
  await group('S07-reduced-generation', { motion: 'reduce' }, async (run) => {
    const { page, s } = run
    s.messages = [
      message({
        reply: '',
        job: job({
          state: 'running',
          stage: 'executing',
          imageGeneration: [
            { operation: 1, state: 'generating', width: 2048, height: 2048 },
            { operation: 2, state: 'queued', width: 2048, height: 2048 },
          ],
        }),
      }),
    ]
    await goto(run)
    await page.getByRole('list', { name: '生成图片' }).waitFor()
    await capture(run, 'S07', 'reduced-image-1')
    await page.waitForTimeout(400)
    await capture(run, 'S07', 'reduced-image-2')
  })
}
if (which === 'gap-only') {
  await group('M03-history-pages', {}, async (run) => {
    const { page, s } = run
    const history = Array.from({ length: 48 }, (_, n) =>
      message({
        id: 'history-message-' + n,
        text: '历史问题 ' + n,
        reply: '历史回复 ' + n + '：保留详细说明，便于检查长历史翻页和位置。',
        createdAt: new Date(Date.UTC(2026, 9, 17, 1, 0) - n * 60000).toISOString(),
      }),
    )
    s.messages = history.slice(0, 24)
    s.moreMessages = history.slice(24)
    s.moreConversations = Array.from({ length: 8 }, (_, n) => ({
      id: 'older-conversation-' + n,
      title: '更早会话 ' + n,
      revision: 1,
      personaId: 'dabao',
      updatedAt: '2026-09-01T01:00:00Z',
    }))
    await goto(run)
    const older = page.getByRole('button', { name: '加载更早消息', exact: true })
    await older.scrollIntoViewIfNeeded()
    await capture(run, 'M03', 'history-pagination-before')
    await older.click()
    await expect(older).toHaveCount(0)
    await page.getByText('历史问题 47', { exact: true }).scrollIntoViewIfNeeded()
    await capture(run, 'M03', 'history-pagination-after')
    await page.getByRole('button', { name: '会话列表', exact: true }).click()
    await expect(page.getByRole('button', { name: /^重命名会话：/ })).toHaveCount(8)
    await page.getByRole('button', { name: '加载更多', exact: true }).click()
    await expect(page.getByRole('button', { name: /^重命名会话：/ })).toHaveCount(16)
    await page.getByRole('link', { name: '更早会话 7', exact: true }).scrollIntoViewIfNeeded()
    await capture(run, 'M03', 'conversation-pagination-after')
  })
  await group('M03-persona-frozen', { record: true }, async (run) => {
    const { page, s } = run
    s.sendDelay = 2500
    await goto(run)
    await page.getByRole('textbox', { name: '工作消息' }).fill('发送时保留原人设及草稿')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await expect(page.getByRole('button', { name: /^选择人设/ })).toBeDisabled()
    await expect(page.getByRole('textbox', { name: '工作消息' })).toHaveAttribute('readonly', '')
    await capture(run, 'M03', 'sending-persona-frozen-readonly')
    await expect(page.getByText('整理好了。优先核对关键资料，再完成下一步工作。')).toBeVisible()
    await expect(page.getByRole('button', { name: /^选择人设/ })).toBeEnabled()
    await capture(
      run,
      'M03',
      'send-accepted-persona-restored',
      '当前实现冻结范围是发送事务；不声称模型整个执行期间均禁止选择人设。',
    )
  })
  await group('M03-readonly-source', { role: 'admin' }, async (run) => {
    const { page, s } = run
    s.messages = [
      message({
        ownerId: 'other-employee',
        text: '同事的只读原始上报',
        transcript: '这段语音记录仅用于阅读。',
        transcriptRevision: 1,
        attachments: [attachment('audio', 'audio-readonly', '只读语音.wav')],
      }),
    ]
    await page.goto(origin + '/messages/audit-message')
    await page.getByRole('heading', { name: '原始上报', exact: true }).waitFor()
    await expect(page.getByText('同事的只读原始上报')).toBeVisible()
    await expect(page.getByRole('textbox', { name: '工作消息' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '改文字', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '补充', exact: true })).toHaveCount(0)
    await capture(
      run,
      'M03',
      'readonly-other-message',
      '会话没有独立只读DTO；非本人消息实际只读入口为SourcePage。',
    )
  })
  await group('M04-reference-entry', {}, async (run) => {
    const { page, s } = run
    await goto(run)
    await panel(page)
    await page.getByRole('button', { name: '引用工作', exact: true }).click()
    await expect(page.getByText('还没有工作可引用', { exact: true })).toBeVisible()
    await capture(run, 'M04', 'reference-stable-empty')
    await closeModal(page)
    const work = {
      id: 'reference-work',
      ownerId: 'audit-owner',
      title: '引用的长工作标题用于入口检查',
      summary: '合成工作说明',
      status: 'in_progress',
      nextStep: '核对资料',
      blocker: '',
      sourceIds: [],
      materialIds: [],
      history: [],
      revision: 1,
      updatedAt: '2026-10-17T01:00:00Z',
    }
    s.referenceWorks = [work]
    await page.reload()
    await page.getByRole('textbox', { name: '工作消息' }).waitFor()
    await panel(page)
    await page.getByRole('button', { name: '引用工作', exact: true }).click()
    await page.getByRole('button', { name: '引用 ' + work.title, exact: true }).waitFor()
    await capture(run, 'M04', 'reference-stable-list')
    await page.getByRole('button', { name: '引用 ' + work.title, exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(page.getByRole('button', { name: '移除工作引用', exact: true })).toBeVisible()
    await capture(run, 'M04', 'reference-in-composer')
    s.messages = [message({ workReference: { workId: work.id, title: work.title } })]
    await page.reload()
    await page.getByRole('link', { name: work.title, exact: true }).click()
    await page.waitForURL('**/work/reference-work')
    await page.getByRole('heading', { name: work.title, exact: true }).waitFor()
    await capture(
      run,
      'M06',
      'work-reference-destination',
      '仅验证引用到工作页入口，工作详情完整布局引用business组证据。',
    )
  })
  await group('M06-deliverable-entry', {}, async (run) => {
    const { page, s } = run
    s.deliverable = {
      id: 'audit-result',
      title: '文件整理结果',
      revision: 1,
      latestRevision: 1,
      messageId: 'audit-message',
      itemCount: 1,
      updatedAt: '2026-10-17T01:00:00Z',
      files: [],
      body: '这是一次合成审计成果。',
      items: [{ id: 'item-one', title: '首先核对资料', body: '保持原始资料与工作记录对应。' }],
      links: [],
    }
    s.messages = [
      message({
        deliverables: [s.deliverable],
        webSources: [
          {
            url: 'https://example.com/audit-reference',
            title: '合成外部来源入口',
            refetchFailed: false,
          },
        ],
      }),
    ]
    await goto(run)
    await page.getByRole('button', { name: '查看文件整理结果', exact: true }).click()
    await page
      .getByRole('dialog', { name: '文件整理结果' })
      .getByText('这是一次合成审计成果。')
      .waitFor()
    await capture(run, 'M06', 'deliverable-entry-open')
    await page.getByRole('button', { name: '继续修改', exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await capture(run, 'M06', 'deliverable-back-to-composer')
    await page.getByText('本轮读取的网页 · 1', { exact: true }).click()
    const link = page.getByRole('link', { name: /合成外部来源入口/ })
    await expect(link).toHaveAttribute('href', 'https://example.com/audit-reference')
    await expect(link).toHaveAttribute('target', '_blank')
    await capture(run, 'M06', 'web-source-entry', '仅核对安全外链入口和target，不向外站发送请求。')
  })
}
if (which === 'webkit-gaps' || which === 'webkit-media') {
  await group(
    which === 'webkit-media' ? 'WebKit-audio-preview-supplement' : 'WebKit-upload-audio-preview',
    { browserName: 'webkit', theme: 'dark', record: true },
    async (run) => {
      const { page, s } = run
      await goto(run)
      if (which === 'webkit-gaps') {
        s.uploadFailures = 1
        await page
          .locator('input[type=file]')
          .last()
          .setInputFiles({
            name: 'WebKit上传与重试.md',
            mimeType: 'text/markdown',
            buffer: Buffer.from('controlled WebKit upload'),
          })
        await page.getByRole('button', { name: /重试上传/ }).waitFor()
        await capture(run, 'M05', 'webkit-upload-failed')
        await page.getByRole('button', { name: /重试上传/ }).click()
        await expect.poll(() => s.uploads.size).toBe(1)
        await expect(page.getByRole('button', { name: /重试上传/ })).toHaveCount(0)
        await capture(run, 'M05', 'webkit-upload-ready')
        await page.getByRole('textbox', { name: '工作消息' }).fill('读取这份合成附件')
        await page.getByRole('button', { name: '发送', exact: true }).click()
        await expect(page.getByText('整理好了。优先核对关键资料，再完成下一步工作。')).toBeVisible()
        await capture(run, 'J03', 'webkit-upload-sent', '受控上传/回复，不代表真实worker提取。')
      }
      s.messages = [
        message({
          text: 'WebKit已有语音',
          transcript: '固定转写，核对资料。',
          transcriptRevision: 1,
          attachments: [attachment('audio', 'audio-webkit', 'webkit.wav')],
        }),
      ]
      await page.reload()
      await page.getByRole('button', { name: '播放webkit.wav', exact: true }).click()
      await page.waitForTimeout(250)
      await capture(run, 'M05', 'webkit-audio-playing-1')
      await page.waitForTimeout(350)
      await capture(run, 'M05', 'webkit-audio-playing-2')
      await page.getByRole('button', { name: '转文字', exact: true }).click()
      await expect(page.getByText('固定转写，核对资料。')).toBeVisible()
      await capture(run, 'M05', 'webkit-audio-transcript')
      await page.getByRole('button', { name: '改文字', exact: true }).click()
      await page.getByRole('dialog', { name: '修正语音文字' }).waitFor()
      await capture(run, 'M05', 'webkit-audio-correcting')
      await page.getByRole('textbox', { name: '语音文字' }).fill('WebKit修正后的固定文字')
      await page.getByRole('button', { name: '保存修正' }).click()
      await expect(page.getByText('WebKit修正后的固定文字')).toBeVisible()
      await capture(
        run,
        'M05',
        'webkit-audio-corrected',
        '固定WAV/预制转写，未使用物理麦克风或真实ASR。',
      )
      const file = {
        id: 'webkit-image',
        name: 'WebKit合成图片.png',
        mimeType: 'image/png',
        size: previewPng.length,
        width: 240,
        height: 240,
        url: '/api/v1/deliverables/images/files/webkit-image?revision=1',
      }
      s.messages = [
        message({
          reply: '图片已完成。',
          deliverables: [
            {
              id: 'images',
              title: 'WebKit合成成果',
              revision: 1,
              latestRevision: 1,
              messageId: 'audit-message',
              itemCount: 1,
              updatedAt: '2026-10-17T01:00:00Z',
              files: [file],
            },
          ],
        }),
      ]
      await page.reload()
      const list = page.getByRole('list', { name: '生成图片' })
      await expect(list.locator('img')).toHaveCount(1)
      await list.getByRole('button').first().click()
      await expect(page.getByRole('dialog').getByRole('img')).toBeVisible()
      await capture(run, 'J06', 'webkit-image-preview')
      await page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).click()
      await expect(page.getByRole('dialog')).toHaveCount(0)
      await capture(run, 'J06', 'webkit-image-preview-closed')
    },
  )
}
console.log(JSON.stringify(results, null, 2))
