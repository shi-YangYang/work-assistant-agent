import type { LucideIcon } from 'lucide-react'
import { ArrowUpRight, Search, X } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'

export interface WebCommand {
  id: string
  label: string
  detail: string
  group: string
  icon: LucideIcon
  current?: boolean
  run: () => void
}

export function CommandPalette({
  commands,
  onClose,
}: {
  commands: WebCommand[]
  onClose: () => void
}) {
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState(0)
  const dialog = useRef<HTMLDialogElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const restoreFocus = useRef(true)
  const listId = useId()
  const filtered = commands.filter((command) =>
    `${command.label} ${command.detail} ${command.group}`
      .toLowerCase()
      .includes(query.trim().toLowerCase()),
  )
  const activeIndex = Math.min(selected, filtered.length - 1)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const element = dialog.current
    element?.showModal()
    input.current?.focus()
    return () => {
      element?.close()
      if (restoreFocus.current && previous?.isConnected) previous.focus()
    }
  }, [])
  useEffect(() => {
    dialog.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex, query])
  const execute = (command: WebCommand) => {
    restoreFocus.current = false
    dialog.current?.close()
    onClose()
    command.run()
  }
  return (
    <dialog
      ref={dialog}
      className="command-dialog"
      aria-label="查找页面与操作"
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="command-search">
        <Search size={20} aria-hidden="true" />
        <input
          ref={input}
          role="combobox"
          aria-label="查找页面与操作"
          aria-expanded="true"
          aria-autocomplete="list"
          aria-controls={listId}
          aria-activedescendant={activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined}
          placeholder="搜索页面或操作…"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value)
            setSelected(0)
          }}
          onKeyDown={(event) => {
            if (event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
              event.preventDefault()
              if (filtered.length)
                setSelected(
                  (activeIndex + (event.key === 'ArrowDown' ? 1 : -1) + filtered.length) %
                    filtered.length,
                )
            } else if (event.key === 'Enter') {
              event.preventDefault()
              if (!event.repeat && filtered[activeIndex]) execute(filtered[activeIndex])
            }
          }}
        />
        <button className="icon-button" aria-label="关闭命令面板" onClick={onClose}>
          <X size={18} />
        </button>
      </div>
      <div className="command-results" role="listbox" id={listId} aria-label="页面与操作">
        {filtered.map((command, index) => (
          <div key={command.id}>
            {(index === 0 || command.group !== filtered[index - 1].group) && (
              <p className="command-group">{command.group}</p>
            )}
            <button
              className="command-result"
              id={`${listId}-${index}`}
              role="option"
              aria-selected={index === activeIndex}
              tabIndex={-1}
              onMouseMove={() => setSelected(index)}
              onClick={() => execute(command)}
            >
              <span className="command-icon">
                <command.icon size={19} />
              </span>
              <span className="command-copy">
                <strong>{command.label}</strong>
                <small>{command.detail}</small>
              </span>
              {command.current ? (
                <span className="command-current">当前</span>
              ) : (
                <ArrowUpRight className="command-arrow" size={16} />
              )}
            </button>
          </div>
        ))}
        {!filtered.length && (
          <div className="command-empty">
            <Search size={24} />
            <strong>没有匹配的页面或操作</strong>
            <span>试试“会话”“工作”或“模型”</span>
          </div>
        )}
      </div>
      <footer className="command-footer">
        <span>
          <kbd>↑</kbd>
          <kbd>↓</kbd> 选择
        </span>
        <span>
          <kbd>Enter</kbd> 打开
        </span>
        <span>
          <kbd>Esc</kbd> 关闭
        </span>
      </footer>
    </dialog>
  )
}
