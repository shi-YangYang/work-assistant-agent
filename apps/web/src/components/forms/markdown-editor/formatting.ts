export type MarkdownFormat = 'heading' | 'bold' | 'italic' | 'bullet' | 'ordered' | 'link' | 'code'

export function formatMarkdown(value: string, start: number, end: number, format: MarkdownFormat) {
  const replace = (from: number, to: number, text: string, offset = 0, length = text.length) => ({
    value: value.slice(0, from) + text + value.slice(to),
    start: from + offset,
    end: from + offset + length,
  })
  const selected = value.slice(start, end)
  if (format === 'heading' || format === 'bullet' || format === 'ordered') {
    const from = start === 0 ? 0 : value.lastIndexOf('\n', start - 1) + 1
    const last = end > start && value[end - 1] === '\n' ? end - 1 : end
    const newline = value.indexOf('\n', last)
    const to = newline < 0 ? value.length : newline
    const lines = value.slice(from, to).split('\n')
    const marker = format === 'heading' ? /^##\s/ : format === 'bullet' ? /^-\s/ : /^\d+\.\s/
    const remove = lines.every((line) => marker.test(line))
    const text = lines
      .map((line, index) => {
        if (remove) return line.replace(marker, '')
        const content = line.replace(/^(?:#{1,6}|[-*+]|\d+[.)])\s+/, '')
        const prefix = format === 'heading' ? '## ' : format === 'bullet' ? '- ' : `${index + 1}. `
        return prefix + (content || (format === 'heading' ? '标题' : '列表项'))
      })
      .join('\n')
    return replace(from, to, text)
  }
  if (format === 'link') {
    const label = selected || '链接文字'
    return replace(start, end, `[${label}](https://)`, label.length + 3, 8)
  }
  if (format === 'code') {
    const content = selected || '代码'
    const longestFence = Math.max(
      2,
      ...Array.from(content.matchAll(/`+/g), (match) => match[0].length),
    )
    const fence = '`'.repeat(longestFence + 1)
    const before = start > 0 && value[start - 1] !== '\n' ? '\n\n' : ''
    const after = end < value.length && value[end] !== '\n' ? '\n\n' : ''
    return replace(
      start,
      end,
      `${before}${fence}\n${content}\n${fence}${after}`,
      before.length + fence.length + 1,
      content.length,
    )
  }
  const marker = format === 'bold' ? '**' : '*'
  if (
    selected &&
    value.slice(Math.max(0, start - marker.length), start) === marker &&
    value.slice(end, end + marker.length) === marker
  )
    return replace(start - marker.length, end + marker.length, selected)
  if (
    selected.length > marker.length * 2 &&
    selected.startsWith(marker) &&
    selected.endsWith(marker)
  )
    return replace(start, end, selected.slice(marker.length, -marker.length))
  const content = selected || (format === 'bold' ? '加粗文字' : '斜体文字')
  return replace(start, end, `${marker}${content}${marker}`, marker.length, content.length)
}
