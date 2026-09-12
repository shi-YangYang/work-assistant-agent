import React, { type ReactNode } from 'react'

// Replies are untrusted text. Build React nodes directly: never interpret HTML
// or embed an image, and only expose explicitly allowed link protocols.
function inline(text: string, depth = 0): ReactNode[] {
  if (depth > 4) return [text]
  const pattern =
    /(`[^`\n]+`|!\[[^\]\n]*\]\([^\n]*?\)|\[[^\]\n]+\]\([^\s\n]*?\)|\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\n]+\*|_[^_\n]+_)/g
  const result: ReactNode[] = []
  let offset = 0
  for (const match of text.matchAll(pattern)) {
    const index = match.index!
    result.push(text.slice(offset, index))
    const token = match[0]
    if (token.startsWith('`')) result.push(<code key={index}>{token.slice(1, -1)}</code>)
    else if (token.startsWith('![')) result.push(token)
    else if (token.startsWith('[')) {
      const separator = token.indexOf('](')
      const label = token.slice(1, separator)
      const href = token.slice(separator + 2, -1)
      let safe = false
      try {
        const url = new URL(href)
        safe =
          ['https:', 'http:', 'mailto:'].includes(url.protocol) &&
          ![...href].some(
            (character) => character.charCodeAt(0) <= 32 || character.charCodeAt(0) === 127,
          )
      } catch {
        /* Unsupported links remain readable text. */
      }
      result.push(
        safe ? (
          <a key={index} href={href} target="_blank" rel="noreferrer noopener">
            {inline(label, depth + 1)}
          </a>
        ) : (
          token
        ),
      )
    } else if (token.startsWith('**') || token.startsWith('__')) {
      result.push(<strong key={index}>{inline(token.slice(2, -2), depth + 1)}</strong>)
    } else result.push(<em key={index}>{inline(token.slice(1, -1), depth + 1)}</em>)
    offset = index + token.length
  }
  result.push(text.slice(offset))
  return result
}

export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r\n?/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let index = 0
  const startsBlock = (line: string) => /^(?:\s*$|```|#{1,6}\s|\s*[-*+]\s|\s*\d+[.)]\s)/.test(line)
  while (index < lines.length) {
    const line = lines[index]
    const key = index
    if (!line.trim()) {
      index++
      continue
    }
    if (line.startsWith('```')) {
      const code: string[] = []
      index++
      while (index < lines.length && !lines[index].startsWith('```')) code.push(lines[index++])
      if (index < lines.length) index++
      blocks.push(
        <pre key={key}>
          <code>{code.join('\n')}</code>
        </pre>,
      )
      continue
    }
    const heading = line.match(/^#{1,6}\s+(.+)$/)
    if (heading) {
      blocks.push(<h4 key={key}>{inline(heading[1])}</h4>)
      index++
      continue
    }
    const list = line.match(/^\s*([-*+]|\d+[.)])\s+(.+)$/)
    if (list) {
      const ordered = /^\d/.test(list[1])
      const items: ReactNode[] = []
      while (index < lines.length) {
        const item = lines[index].match(/^\s*([-*+]|\d+[.)])\s+(.+)$/)
        if (!item || /^\d/.test(item[1]) !== ordered) break
        items.push(<li key={index}>{inline(item[2])}</li>)
        index++
      }
      blocks.push(
        ordered ? (
          <ol key={key} start={parseInt(list[1])}>
            {items}
          </ol>
        ) : (
          <ul key={key}>{items}</ul>
        ),
      )
      continue
    }
    const paragraph = [line]
    index++
    while (index < lines.length && !startsBlock(lines[index])) paragraph.push(lines[index++])
    blocks.push(<p key={key}>{inline(paragraph.join('\n'))}</p>)
  }
  return <div className="markdown">{blocks}</div>
}
