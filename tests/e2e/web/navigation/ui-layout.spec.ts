import { readFileSync } from 'node:fs'
import type { Locator, Page } from '@playwright/test'
import type { Report } from '@paa/api-contracts'
import { test, expect } from '../fixtures/test'

type Records = Record<
  'admin' | 'employee',
  { work: string; conversation: string; message: string; daily: string; weekly: string }
>

function records(): Records {
  return JSON.parse(
    readFileSync(process.env.UI_LAYOUT_RECORDS || 'artifacts/spec050/records.json', 'utf8'),
  ) as Records
}

async function theme(page: Page, value: '浅色' | '深色') {
  await page.getByRole('button', { name: 'Noria 外观', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Noria 外观', exact: true })
  await dialog.getByRole('button', { name: value, exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
}

async function unobscured(target: Locator) {
  await expect(target).toBeVisible()
  const result = await target.evaluate((node) => {
    const range = document.createRange()
    range.selectNodeContents(node)
    const rect = /^H[1-6]$/.test(node.tagName)
      ? range.getBoundingClientRect()
      : node.getBoundingClientRect()
    const points = [0.2, 0.5, 0.8].map((ratio) => ({
      x: rect.left + rect.width * ratio,
      y: rect.top + rect.height / 2,
    }))
    return points.every(({ x, y }) => node.contains(document.elementFromPoint(x, y)))
  })
  expect(result, 'control hit area is not covered by navigation or pet').toBe(true)
}

for (const role of ['admin', 'employee'] as const) {
  test(`UI-01 ${role} Markdown headers retain readable contrast in both themes`, async ({
    page,
    state,
    login,
    capture,
  }) => {
    await login(role)
    const ids = records()[role]
    for (const path of [`/assistant/${ids.conversation}`, `/messages/${ids.message}`]) {
      await page.goto(state.origin + path)
      const headers = page.locator('table thead th')
      await expect(headers.first()).toBeVisible()
      for (const width of [1440, 390]) {
        await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 })
        for (const value of ['浅色', '深色'] as const) {
          await theme(page, value)
          const ratios = await headers.evaluateAll((nodes) => {
            const parse = (value: string) => {
              const numbers = value.match(/[\d.]+/g)?.map(Number) ?? []
              return [numbers[0] ?? 0, numbers[1] ?? 0, numbers[2] ?? 0, numbers[3] ?? 1]
            }
            const blend = (foreground: number[], background: number[]) =>
              foreground
                .slice(0, 3)
                .map(
                  (channel, index) =>
                    channel * foreground[3] + background[index] * (1 - foreground[3]),
                )
            const luminance = (rgb: number[]) =>
              rgb.reduce((sum, channel, index) => {
                const value = channel / 255
                const linear = value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
                return sum + linear * [0.2126, 0.7152, 0.0722][index]
              }, 0)
            return nodes.map((node) => {
              const chain: Element[] = []
              for (let ancestor: Element | null = node; ancestor; ancestor = ancestor.parentElement)
                chain.unshift(ancestor)
              let background = [255, 255, 255]
              for (const ancestor of chain)
                background = blend(parse(getComputedStyle(ancestor).backgroundColor), background)
              const foreground = blend(parse(getComputedStyle(node).color), background)
              const a = luminance(background)
              const b = luminance(foreground)
              return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
            })
          })
          for (const ratio of ratios)
            expect(ratio, `${role} ${path} ${value}`).toBeGreaterThanOrEqual(4.5)
          await capture(
            `markdown-${path.startsWith('/messages') ? 'source' : 'chat'}-${width}-${value}`,
          )
        }
      }
    }
  })

  test(`UI-02 UI-04 ${role} historical return remains reachable and returns to latest`, async ({
    page,
    state,
    login,
    capture,
  }) => {
    await login(role)
    const id = records()[role].work
    for (const width of [360, 390, 768, 1024]) {
      await page.setViewportSize({ width, height: 844 })
      for (const value of ['浅色', '深色'] as const) {
        await page.goto(`${state.origin}/work/${id}?revision=1`)
        const back = page.getByRole('link', { name: '返回最新版本', exact: true })
        await expect(back).toBeVisible()
        await theme(page, value)
        await unobscured(back)
        const heading = page.getByRole('heading', { level: 2 })
        await expect(heading).toBeVisible()
        await unobscured(heading)
        await expect(page.getByText('历史版本 · 第 1 版', { exact: true })).toBeVisible()
        await capture(`history-${width}-${value}`)
        await back.click()
        await expect(page).toHaveURL(`${state.origin}/work/${id}`)
        await expect(page.getByRole('button', { name: '编辑内容', exact: true })).toBeVisible()
      }
    }
  })
}

test('UI-03 team work and report drawers use their own width', async ({
  page,
  state,
  login,
  capture,
}) => {
  await login()
  const ids = records().employee
  for (const width of [360, 390, 1440]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 })
    for (const value of ['浅色', '深色'] as const) {
      await theme(page, value)
      for (const [kind, id] of [
        ['work', ids.work],
        ['reports', ids.daily],
      ]) {
        await page.goto(`${state.origin}/team?view=${kind}&record=${id}`)
        const modal = page.getByRole('dialog', { name: kind === 'work' ? '工作详情' : '报告详情' })
        const heading = modal.getByRole('heading', { level: 2 }).last()
        await expect(heading).toBeVisible()
        const geometry = await heading.evaluate((node) => {
          const rect = node.getBoundingClientRect()
          const compact = node.closest('[data-compact="true"]')!
          const parent = compact.getBoundingClientRect()
          const available = node.parentElement!.getBoundingClientRect()
          const style = getComputedStyle(node)
          const range = document.createRange()
          range.selectNodeContents(node)
          const fragments = [...range.getClientRects()].filter((fragment) => fragment.width > 0)
          return {
            width: rect.width,
            parentWidth: parent.width,
            availableWidth: available.width,
            maxWidth: style.maxWidth === 'none' ? null : parseFloat(style.maxWidth),
            textFits: fragments.every(
              (fragment) =>
                fragment.left >= rect.left - 1 &&
                fragment.right <= rect.right + 1 &&
                fragment.top >= rect.top - 1 &&
                fragment.bottom <= rect.bottom + 1,
            ),
            textLines: new Set(fragments.map((fragment) => Math.round(fragment.top))).size,
            left: rect.left - parent.left,
            marginLeft: parseFloat(style.marginLeft),
          }
        })
        expect(
          geometry.availableWidth,
          'drawer title row has usable width, independent of short title text',
        ).toBeGreaterThanOrEqual(Math.min(240, geometry.parentWidth * 0.75))
        if (geometry.maxWidth !== null)
          expect(geometry.maxWidth, 'no inherited 95px page title limit').toBeGreaterThanOrEqual(
            geometry.availableWidth - 1,
          )
        expect(geometry.textFits, 'all title text remains inside its own bounds').toBe(true)
        if (kind === 'reports')
          expect(geometry.textLines, 'short report date stays on one line').toBe(1)
        expect(geometry.left, 'drawer title starts on its own content edge').toBeLessThanOrEqual(20)
        expect(geometry.marginLeft, 'no inherited mobile navigation offset').toBeLessThanOrEqual(1)
        expect(geometry.width).toBeLessThanOrEqual(geometry.parentWidth)
        await capture(`drawer-${kind}-${width}-${value}`)
        await page.keyboard.press('Escape')
        await expect(modal).toHaveCount(0)
      }
    }
  }
})

test('UI-11 usage table exposes all columns with a stable key column and scroll hint', async ({
  page,
  state,
  login,
  capture,
}) => {
  await login()
  await page.goto(state.origin + '/settings/usage')
  await expect(page.locator('table tbody tr').first()).toBeVisible()
  for (const value of ['浅色', '深色'] as const) {
    await theme(page, value)
    for (const width of [360, 390]) {
      // Resizing while the scroll region retains keyboard focus can move it into view.
      await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
      await page.setViewportSize({ width, height: 844 })
      const table = page.locator('table')
      const region = page.getByRole('region', { name: '模型调用记录', exact: true })
      await expect(region).toHaveAttribute('tabindex', '0')
      await region.evaluate((node) => node.scrollTo({ left: 0, behavior: 'instant' }))
      await expect.poll(() => region.evaluate((node) => node.scrollLeft)).toBe(0)
      const first = table.locator('tbody tr').first().locator('td').first()
      const before = await first.boundingBox()
      expect(before).not.toBeNull()
      await expect(page.getByText('向右滑动查看更多列', { exact: true })).toBeVisible()
      await region.focus()
      await expect(region).toBeFocused()
      // Native keyboard scrolling animates even with reduced motion. Finish it
      // before jumping to the opposite edge or resizing the next scenario.
      const scrollEnded = region.evaluate(
        (node) =>
          new Promise<void>((done) =>
            node.addEventListener('scrollend', () => done(), { once: true }),
          ),
      )
      await page.keyboard.press('ArrowRight')
      await scrollEnded
      await expect.poll(() => region.evaluate((node) => node.scrollLeft)).toBeGreaterThan(0)
      await region.evaluate((node) => node.scrollTo(node.scrollWidth, 0))
      await expect
        .poll(() =>
          region.evaluate((node) => node.scrollWidth - node.clientWidth - node.scrollLeft),
        )
        .toBeLessThanOrEqual(1)
      const after = await first.boundingBox()
      expect(Math.abs(after!.x - before!.x)).toBeLessThanOrEqual(1)
      await expect(page.getByText('向左滑动查看前面的列', { exact: true })).toBeVisible()
      const last = table.locator('thead th').last()
      const bounds = await last.boundingBox()
      expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width)
      await capture(`usage-scrolled-${width}-${value}`)
    }
  }
  await page.setViewportSize({ width: 1440, height: 1000 })
  await expect(page.getByText(/滑动查看/)).toHaveCount(0)
})

test('UI workflow employee edits and submits a seeded report, then admin reads it', async ({
  page,
  state,
  login,
  http,
  capture,
}) => {
  await login('employee')
  const id = records().employee.weekly
  await page.goto(`${state.origin}/reports/${id}`)
  await page.getByRole('button', { name: '编辑草稿', exact: true }).click()
  await page.getByLabel('完成的工作').fill('完成排版验证，核对桌面与手机的核心流程。')
  await page.getByLabel('问题与阻碍').fill('暂无阻碍')
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await expect(page.getByText('草稿已保存', { exact: true })).toBeVisible()
  const saved = await http<Report>(`/api/v1/reports/${id}`)
  expect(saved.status).toBe(200)
  await page.getByRole('button', { name: '提交报告', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: '确认提交', exact: true }).click()
  await expect(page.getByText(`已提交第 ${saved.data.revision} 版`, { exact: true })).toBeVisible()
  const published = await http<Report>(`/api/v1/reports/${id}`)
  expect(published.data.publishedRevision).toBe(saved.data.revision)
  expect(published.data.content.completed).toBe('完成排版验证，核对桌面与手机的核心流程。')
  await capture('employee-report-published')
  await page.goto(state.origin + '/settings/account')
  await page.getByRole('button', { name: '退出登录', exact: true }).last().click()
  await login()
  await page.goto(`${state.origin}/reports/${id}`)
  await expect(
    page.getByText('完成排版验证，核对桌面与手机的核心流程。', { exact: true }),
  ).toBeVisible()
  await expect(page.getByRole('button', { name: '编辑草稿', exact: true })).toHaveCount(0)
  await capture('admin-published-report')
})
