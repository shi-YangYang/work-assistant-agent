import type { DeliverableSummary } from '@paa/api-contracts'
import { expect, it } from 'vitest'
import { compactImageReferences } from '../../../apps/web/src/features/assistant/components/messages/reply/image-references'

const url = '/api/v1/deliverables/image-task/files/file-1?revision=2'
const item: DeliverableSummary = {
  id: 'image-task',
  revision: 2,
  latestRevision: 2,
  title: '四张山水图',
  messageId: 'message',
  itemCount: 0,
  updatedAt: '2026-10-14T00:00:00Z',
  files: [{ id: 'file-1', name: 'image-1.png', mimeType: 'image/png', size: 100, url }],
}
it('removes only redundant exact file references while keeping the image descriptions', () => {
  const reply = `已生成图片。\n\n1. 圆月孤舟\n   ${url}\n\n2. 深谷飞瀑\n[查看深谷]( ${url})\n[圆月孤舟](${url})\n![图像说明](${url})`
  expect(compactImageReferences(reply, [item])).toBe(
    `已生成图片。\n\n1. 圆月孤舟\n\n\n2. 深谷飞瀑\n[查看深谷]( ${url})\n圆月孤舟\n图像说明`,
  )
  expect(compactImageReferences(`\`${url}\`\n<${url}>`, [item])).toBe(`\`${url}\`\n`)
})

it.each([
  ['```http', '```'],
  ['~~~http', '~~~'],
  ['  ```http', '   ```'],
  ['   ~~~~http', ' ~~~~~'],
  ['> ```http', '> ```'],
])(
  'preserves fenced code verbatim for %s while compacting references outside it',
  (open, close) => {
    const code = `${open}\n${url}\n[下载](${url})\n${close}`
    expect(compactImageReferences(`${url}\n${code}\n${url}`, [item])).toBe(`\n${code}\n`)
  },
)

it('does not end a fence at shorter, mismatched or non-closing delimiters', () => {
  const code = `\`\`\`\`http\n\`\`\`\n${url}\n~~~~\n[下载](${url})\n\`\`\`\` trailing text\n${url}\n\`\`\`\``
  expect(compactImageReferences(`${code}\n${url}`, [item])).toBe(`${code}\n`)
  expect(compactImageReferences(`~~~\n${url}\n[下载](${url})`, [item])).toBe(
    `~~~\n${url}\n[下载](${url})`,
  )
})

it.each(['`', '``', '```', '````'])('preserves inline code with %s delimiters', (delimiter) => {
  const code = `${delimiter}[下载](${url})${delimiter}`
  const content = `示例 ${code}，图片：[下载](${url})\n${delimiter}${url}${delimiter}`
  expect(compactImageReferences(content, [item])).toBe(
    `示例 ${code}，图片：下载\n${delimiter}${url}${delimiter}`,
  )
})

it('preserves multiline code spans and embedded shorter backtick runs', () => {
  const code = `\`\`示例 \`[下载](${url})\`\n    ${url}\n${url}\n\`\``
  expect(compactImageReferences(`文本 ${code}\n${url}\n[下载](${url})`, [item])).toBe(
    `文本 ${code}\n\n下载`,
  )
})

it('preserves indented code and escaped opening backticks without hiding ordinary links', () => {
  const code = `    ${url}\n\t[下载](${url})`
  expect(compactImageReferences(`${code}\n\n${url}`, [item])).toBe(`${code}\n\n`)
  expect(compactImageReferences(`\\\`示例 [下载](${url})\``, [item])).toBe('\\`示例 下载`')
})
it('preserves code, unsupported links, other versions and files not provided by the API', () => {
  const content = `\`\`\`http\n${url}\n\`\`\`\n${url.replace('=2', '=1')}\n${url}/other\n[外部](https://example.com${url})\n[不安全](javascript:alert)\n文字里讨论 ${url}`
  expect(compactImageReferences(content, [item])).toBe(content)
  expect(compactImageReferences(url, [])).toBe(url)
  expect(
    compactImageReferences(url, [
      { ...item, files: [{ ...item.files![0], mimeType: 'text/plain' }] },
    ]),
  ).toBe(url)
})
