import { useEffect, useRef, useState } from 'react'
import { Search, X } from 'lucide-react'

export type Page = 'meetings' | 'current' | 'meeting' | 'services' | 'local-model' | 'appearance'
export type Theme = 'system' | 'light' | 'dark'
export const pageLabels: Record<Page, string> = {
  meetings: '会议记录',
  current: '当前会议',
  meeting: '会议详情',
  services: '模型服务管理',
  'local-model': '本地转写模型',
  appearance: '外观',
}
export function useTheme(): [Theme, (theme: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      const saved = localStorage.getItem('paa.appearance.theme')
      if (saved === 'light' || saved === 'dark') return saved
    } catch {
      /* Optional preference. */
    }
    return 'system'
  })
  useEffect(() => {
    const system = matchMedia('(prefers-color-scheme: dark)')
    const apply = (): void => {
      document.documentElement.dataset.theme =
        theme === 'system' ? (system.matches ? 'dark' : 'light') : theme
    }
    apply()
    system.addEventListener('change', apply)
    try {
      localStorage.setItem('paa.appearance.theme', theme)
    } catch {
      /* Optional preference. */
    }
    return () => system.removeEventListener('change', apply)
  }, [theme])
  return [theme, setTheme]
}
export function Appearance({
  theme,
  onChange,
}: {
  theme: Theme
  onChange: (value: Theme) => void
}): React.JSX.Element {
  return (
    <section className="settings-card appearance-card" aria-label="外观设置">
      <h2>显示主题</h2>
      <p>选择适合当前环境的外观，跟随系统会自动切换。</p>
      <fieldset className="theme-options">
        <legend>主题</legend>
        {(
          [
            ['system', '跟随系统'],
            ['light', '浅色'],
            ['dark', '深色'],
          ] as const
        ).map(([value, label]) => (
          <label key={value} className={`theme-option ${theme === value ? 'selected' : ''}`}>
            <span className={`theme-preview ${value}`} aria-hidden="true">
              <span />
              <span />
            </span>
            <span>
              <input
                type="radio"
                name="theme"
                value={value}
                checked={theme === value}
                onChange={() => onChange(value)}
              />
              {label}
            </span>
          </label>
        ))}
      </fieldset>
    </section>
  )
}
export type Command = {
  id: string
  label: string
  detail: string
  disabled?: boolean
  run: () => void
}
export function CommandPalette({
  commands,
  onClose,
}: {
  commands: Command[]
  onClose: () => void
}): React.JSX.Element {
  const [query, setQuery] = useState('')
  const dialog = useRef<HTMLDialogElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const restoreFocus = useRef(true)
  const filtered = commands.filter((command) =>
    `${command.label} ${command.detail}`.toLowerCase().includes(query.toLowerCase()),
  )
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const element = dialog.current
    element?.showModal()
    input.current?.focus()
    return () => {
      element?.close()
      if (restoreFocus.current && previous?.isConnected && !previous.closest('[hidden]'))
        previous.focus()
    }
  }, [])
  const execute = (command: Command): void => {
    // Release the modal synchronously before navigation focuses its destination.
    // Unmount cleanup must not move focus back after the command has run.
    restoreFocus.current = false
    dialog.current?.close()
    onClose()
    command.run()
  }
  return (
    <dialog
      ref={dialog}
      className="command-dialog"
      aria-label="命令面板"
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
      onKeyDown={(event) => {
        if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
        const choices = Array.from(
          event.currentTarget.querySelectorAll<HTMLButtonElement>('.command-result:not(:disabled)'),
        )
        if (!choices.length) return
        event.preventDefault()
        const index = choices.indexOf(document.activeElement as HTMLButtonElement)
        choices[
          event.key === 'ArrowDown'
            ? (index + 1) % choices.length
            : index <= 0
              ? choices.length - 1
              : index - 1
        ]?.focus()
      }}
    >
      <div className="command-search">
        <Search size={19} />
        <input
          ref={input}
          aria-label="查找页面与操作"
          placeholder="查找页面与操作…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              const command = filtered.find((item) => !item.disabled)
              if (command) execute(command)
            }
          }}
        />
        <button className="icon-button" aria-label="关闭命令面板" onClick={onClose}>
          <X size={18} />
        </button>
      </div>
      <p className="command-caption">页面与操作 · ↑ ↓ 选择 · Enter 执行 · Esc 关闭</p>
      <div className="command-results">
        {filtered.length ? (
          filtered.map((command) => (
            <button
              className="command-result"
              key={command.id}
              disabled={command.disabled}
              onClick={() => execute(command)}
            >
              <strong>{command.label}</strong>
              <small>{command.detail}</small>
            </button>
          ))
        ) : (
          <p className="empty-copy">没有匹配的页面或操作</p>
        )}
      </div>
    </dialog>
  )
}
