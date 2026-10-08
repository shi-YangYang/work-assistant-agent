import type { WebReadSource } from '@paa/api-contracts'
import { ChevronDown, Globe } from 'lucide-react'
import documentsStyles from '@web/components/media/documents.module.css'
import styles from './WebSources.module.css'

function safeSources(sources: WebReadSource[]) {
  const seen = new Set<string>()
  return sources.filter((source) => {
    try {
      const url = new URL(source.url)
      if (
        !['http:', 'https:'].includes(url.protocol) ||
        url.username ||
        url.password ||
        [...source.url].some(
          (character) => character.charCodeAt(0) <= 32 || character.charCodeAt(0) === 127,
        )
      )
        return false
      url.hash = ''
      if (seen.has(url.href)) return false
      seen.add(url.href)
      return true
    } catch {
      return false
    }
  })
}

export function WebSources({ sources }: { sources: WebReadSource[] }) {
  const rows = safeSources(sources)
  if (!rows.length) return null
  return (
    <details className={documentsStyles['document-citations']}>
      <summary>
        <Globe size={14} />
        <span>本轮读取的网页 · {rows.length}</span>
        <ChevronDown size={14} />
      </summary>
      <div className={styles.sources}>
        <p>列出读取过内容的网页，可能只读取了片段；不代表逐条核实了答复。</p>
        {rows.map((source) => (
          <a href={source.url} key={source.url} target="_blank" rel="noreferrer noopener">
            <span>{source.title.slice(0, 200) || source.url}</span>
            <small>
              {new URL(source.url).hostname}
              {source.refetchFailed ? ' · 后续读取未成功' : ''}
            </small>
          </a>
        ))}
      </div>
    </details>
  )
}
