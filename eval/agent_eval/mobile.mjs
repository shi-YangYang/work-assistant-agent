// Read-only mobile inspection of a retained real conversation. No model submission.
import { chromium } from 'playwright'
import fs from 'node:fs/promises'
const [trial, output] = process.argv.slice(2)
const metadata = JSON.parse(await fs.readFile(`${trial}/environment/metadata.json`))
const state = JSON.parse(await fs.readFile(metadata.credentialsFile))
const saved = JSON.parse(await fs.readFile(`${trial}/result.json`))
const conversation = saved.turns[0].receipt.conversationId
await fs.mkdir(output, { recursive: false })
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({
  viewport: { width: 390, height: 844 },
  isMobile: true,
  hasTouch: true,
})
const result = {
  layer: 'real-browser-existing-evidence',
  viewport: { width: 390, height: 844 },
  providerCalls: 0,
  source: trial,
  checks: [],
}
try {
  await page.goto(state.origin)
  await page.getByRole('button', { name: /直接登录/ }).click()
  await page.getByLabel('账号', { exact: true }).fill(state.users[saved.case.role].username)
  await page.getByLabel('密码', { exact: true }).fill(state.users[saved.case.role].password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForURL(/\/work|\/assistant|\/overview|\/team/)
  await page.goto(`${state.origin}/assistant/${conversation}`)
  await page.waitForTimeout(1500)
  result.before = await page.locator('body').innerText()
  result.dimensions = await page.evaluate(() => ({
    width: innerWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))
  await page.screenshot({ path: `${output}/mobile-before.png`, fullPage: true })
  const composer = page.locator('textarea').first()
  await composer.click()
  await composer.fill('移动端固定输入，不发送')
  result.checks.push({
    id: 'composer-interaction',
    status: (await composer.inputValue()) === '移动端固定输入，不发送' ? 'PASS' : 'FAIL',
  })
  await composer.fill('')
  await page.reload()
  await page.waitForTimeout(1000)
  result.after = await page.locator('body').innerText()
  await page.screenshot({ path: `${output}/mobile-reload.png`, fullPage: true })
  result.checks.push({
    id: 'no-horizontal-overflow',
    status: result.dimensions.scrollWidth <= 390 ? 'PASS' : 'FAIL',
  })
  result.checks.push({
    id: 'conversation-refresh',
    status:
      result.before === result.after && result.before.includes(saved.turns[0].prompt)
        ? 'PASS'
        : 'INCOMPLETE',
  })
} catch (error) {
  result.error = error.message
  result.checks.push({ id: 'mobile-observation', status: 'INCOMPLETE' })
} finally {
  await browser.close()
  await fs.writeFile(`${output}/result.json`, JSON.stringify(result, null, 2))
}
