import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import { Markdown } from '../../src/web/Markdown'

const render = (text: string) => renderToStaticMarkup(createElement(Markdown, { text }))

it('renders readable reply paragraphs, emphasis, ordered and unordered lists and code', () => {
  const html = render(
    '### 工作进展\n\n**需求确认**，*等待评审*。\n第二行。\n\n- 第一项\n- `第二项`\n\n1. 周一\n2. 周二\n\n```html\n<div>原始代码</div>\n```',
  )
  expect(html).toContain('<h4>工作进展</h4>')
  expect(html).toContain('<strong>需求确认</strong>，<em>等待评审</em>。\n第二行。')
  expect(html).toContain('<ul><li>第一项</li><li><code>第二项</code></li></ul>')
  expect(html).toContain('<ol start="1"><li>周一</li><li>周二</li></ol>')
  expect(html).toContain('&lt;div&gt;原始代码&lt;/div&gt;')
})

it('never executes reply HTML, embeds remote images, or links to unsafe protocols', () => {
  const html = render(
    '<script>alert(1)</script>\n<img src="https://tracker.test/pixel" onerror="alert(1)">\n\n![远程图片](https://tracker.test/pixel)\n\n[危险](javascript:alert(1)) [编码](javascript&#58;alert) [数据](data:text/html,attack) [文件](file:///etc/passwd) [换行](java\nscript:alert)',
  )
  expect(html).not.toMatch(/<(?:script|img|iframe|a)[\s>]/)
  expect(html).toContain('&lt;script&gt;')
  expect(html).toContain('![远程图片](https://tracker.test/pixel)')
})

it('allows explicit web and mail links without interpreting labels as HTML', () => {
  const html = render(
    '[说明](https://example.com/docs?q=test) [邮件](mailto:work@example.com) [<img>](https://example.com)',
  )
  expect(html).toContain('href="https://example.com/docs?q=test"')
  expect(html).toContain('href="mailto:work@example.com"')
  expect(html).toContain('rel="noreferrer noopener"')
  expect(html).toContain('&lt;img&gt;</a>')
})
