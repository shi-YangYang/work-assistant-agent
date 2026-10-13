import { writeFileSync } from 'node:fs'
import { test, expect } from '../fixtures/test'

test.use({ reducedMotion: 'no-preference', video: 'on' })

test('W20 route loading duration, cached navigation, narrow and low-height controls', async ({
  page,
  browser,
  login,
  state,
  capture,
}, info) => {
  await login()
  const observations: unknown[] = []
  for (const path of ['/work', '/settings/memory', '/work']) {
    await page.evaluate(() => {
      const samples: {
        shown: number | null
        hidden: number | null
        frames: number
        animated: boolean
      } = { shown: null, hidden: null, frames: 0, animated: false }
      Object.assign(window, { loadingObservation: samples })
      const update = () => {
        const label = [...document.querySelectorAll('p')].find(
          (node) => node.textContent === '正在加载页面',
        )
        if (label) {
          samples.shown ??= performance.now()
          samples.frames++
          samples.animated ||= document
            .getAnimations()
            .some((animation) => animation.playState === 'running')
        } else if (samples.shown !== null && samples.hidden === null)
          samples.hidden = performance.now()
        if (samples.hidden === null) requestAnimationFrame(update)
      }
      requestAnimationFrame(update)
    })
    if (path === '/work') {
      const back = page.getByRole('button', { name: '返回主菜单', exact: true })
      if (await back.isVisible()) await back.click()
      await page.getByRole('link', { name: '我的工作', exact: true }).click()
    } else {
      await page.getByRole('button', { name: '系统设置', exact: true }).click()
      await page.getByRole('link', { name: '记忆', exact: true }).click()
    }
    await expect(page.getByText('正在加载页面', { exact: true })).toBeVisible()
    await expect(
      page.getByRole('heading', { name: path === '/work' ? '我的工作' : '记忆', exact: true }),
    ).toBeVisible()
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            (window as unknown as { loadingObservation: { hidden: number | null } })
              .loadingObservation.hidden,
        ),
      )
      .not.toBeNull()
    const result = await page.evaluate(
      () =>
        (
          window as unknown as {
            loadingObservation: { shown: number; hidden: number; frames: number; animated: boolean }
          }
        ).loadingObservation,
    )
    expect(result.hidden - result.shown).toBeGreaterThanOrEqual(280) // requestAnimationFrame samples have a one-frame edge at each boundary.
    expect(result.frames).toBeGreaterThan(3)
    expect(result.animated).toBe(true)
    observations.push({ path, ...result })
  }
  for (const viewport of [
    { width: 360, height: 780 },
    { width: 768, height: 1024 },
    { width: 1280, height: 720 },
    { width: 1920, height: 1080 },
  ]) {
    await page.setViewportSize(viewport)
    await page.goto(state.origin + '/settings/memory')
    await expect(page.getByRole('switch', { name: '启用跨会话记忆' })).toBeVisible()
    await capture(`memory-edge-${viewport.width}x${viewport.height}`)
  }
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto(state.origin + '/settings/models')
  await page.getByRole('tab', { name: '用途分配', exact: true }).click()
  await expect(page.getByRole('heading', { name: '模型服务管理', exact: true })).toBeVisible()
  const routingWidth = await page
    .getByRole('button', { name: '保存用途分配', exact: true })
    .evaluate((node) => node.closest('section')!.getBoundingClientRect().width)
  expect(routingWidth).toBeGreaterThan(1000)
  await capture('routing-full-right-panel')
  // A 1440x1000 physical viewport at 200% browser zoom has a 720x500 CSS viewport.
  // Emulate both CSS viewport and DPR, instead of CSS zoom which leaves media queries unchanged.
  const zoomContext = await browser.newContext({
    viewport: { width: 720, height: 500 },
    deviceScaleFactor: 2,
    reducedMotion: 'no-preference',
    storageState: await page.context().storageState(),
  })
  const zoomPage = await zoomContext.newPage()
  await zoomPage.goto(state.origin + '/settings/models')
  await zoomPage.getByRole('tab', { name: '用途分配', exact: true }).click()
  const zoom = await zoomPage.evaluate(() => ({
    width: innerWidth,
    height: innerHeight,
    dpr: devicePixelRatio,
  }))
  expect(zoom).toEqual({ width: 720, height: 500, dpr: 2 })
  await zoomPage.screenshot({ path: info.outputPath('routing-emulated-browser-zoom-200.png') })
  expect(
    await zoomPage.evaluate(() => document.documentElement.scrollWidth - innerWidth),
  ).toBeLessThanOrEqual(1)
  const overlap = await zoomPage
    .getByRole('heading', { name: '模型服务管理', exact: true })
    .evaluate((node) => {
      const a = node.getBoundingClientRect(),
        b = document.querySelector('button[aria-label="Noria 外观"]')!.getBoundingClientRect()
      return (
        Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) *
        Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top))
      )
    })
  expect(overlap).toBe(0)
  await zoomContext.close()
  observations.push({
    zoom: '200% browser layout emulation; native toolbar action not automated',
    ...zoom,
    routingWidth,
  })
  writeFileSync(info.outputPath('motion-metrics.json'), JSON.stringify(observations, null, 2))
})
