import type { DeliverableSummary } from '@paa/api-contracts'

function compactProse(text: string, urls: Set<string>) {
  const markers = [...text.matchAll(/`+/g)]
  const next = new Map<number, number>()
  const closing = markers.map(() => -1)
  for (let index = markers.length - 1; index >= 0; index--) {
    const length = markers[index][0].length
    closing[index] = next.get(length) ?? -1
    next.set(length, index)
  }
  const code: Array<[number, number]> = []
  for (let index = 0; index < markers.length; index++) {
    const start = markers[index].index!
    let escapes = 0
    for (let cursor = start - 1; cursor >= 0 && text[cursor] === '\\'; cursor--) escapes++
    if (escapes % 2 || closing[index] < 0) continue
    const end = markers[closing[index]]
    code.push([start, end.index! + end[0].length])
    index = closing[index]
  }
  const intersectsCode = (start: number, end: number) =>
    code.some(([codeStart, codeEnd]) => start < codeEnd && end > codeStart)
  let offset = 0
  return text
    .split('\n')
    .map((line) => {
      const start = offset
      offset += line.length + 1
      // Keep indented examples without splitting multiline inline-code spans.
      if (/^(?: {4}| *\t)/.test(line.replace(/^(?: {0,3}>[ \t]?)+/, ''))) return line
      const value = line.trim()
      const wrapped = value.match(/^<([^>]+)>$/)
      if (
        !intersectsCode(start, start + line.length) &&
        (urls.has(value) || (wrapped && urls.has(wrapped[1])))
      )
        return ''
      // Preserve labels, but never rewrite links inside a code example.
      return line.replace(/!?\[([^\]\n]*)\]\(([^\s\n]*?)\)/g, (token, label, href, index) =>
        urls.has(href) && !intersectsCode(start + index, start + index + token.length)
          ? label
          : token,
      )
    })
    .join('\n')
}

// The API's image gallery already owns preview and download. Only compact exact
// references to those files; unknown paths, prose and code examples stay intact.
export function compactImageReferences(text: string, items: DeliverableSummary[] = []) {
  const urls = new Set(
    items.flatMap((item) =>
      (item.files ?? [])
        .filter(
          (file) => file.mimeType === 'image/png' && file.url.startsWith('/api/v1/deliverables/'),
        )
        .map((file) => file.url),
    ),
  )
  if (!urls.size) return text
  const result: string[] = []
  let prose: string[] = []
  let fence: string | null = null
  const flush = () => {
    if (prose.length) result.push(compactProse(prose.join('\n'), urls))
    prose = []
  }
  for (const line of text.split('\n')) {
    // Accept either Markdown fence character and up to three leading spaces.
    // Stripping quote markers also protects code in quoted examples.
    const content = line.replace(/^(?: {0,3}>[ \t]?)+/, '')
    const marker = content.match(/^ {0,3}(`{3,}|~{3,})(.*)$/)
    if (fence) {
      result.push(line)
      if (
        marker &&
        marker[1][0] === fence[0] &&
        marker[1].length >= fence.length &&
        !marker[2].trim()
      )
        fence = null
    } else if (marker && (marker[1][0] === '~' || !marker[2].includes('`'))) {
      flush()
      fence = marker[1]
      result.push(line)
    } else prose.push(line)
  }
  flush()
  return result.join('\n')
}
