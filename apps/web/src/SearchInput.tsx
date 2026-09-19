import { useEffect, useRef, useState, type InputHTMLAttributes } from 'react'

export function SearchInput({
  value,
  onSearch,
  resetKey = 0,
  ...props
}: Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'defaultValue' | 'onChange'> & {
  value: string
  onSearch: (value: string) => void
  resetKey?: number
}) {
  const [draft, setDraft] = useState({ text: value, value, resetKey })
  if (draft.value !== value || draft.resetKey !== resetKey)
    setDraft({ text: value, value, resetKey })
  const composing = useRef(false)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const search = useRef(onSearch)
  useEffect(() => {
    search.current = onSearch
  }, [onSearch])
  useEffect(() => {
    clearTimeout(timer.current)
    composing.current = false
  }, [value, resetKey])
  useEffect(() => () => clearTimeout(timer.current), [])
  const publish = (next: string) => {
    clearTimeout(timer.current)
    if (next !== value) search.current(next)
  }
  const change = (next: string) => {
    setDraft({ text: next, value, resetKey })
    clearTimeout(timer.current)
    if (composing.current) return
    if (!next) publish(next)
    else timer.current = setTimeout(() => publish(next), 300)
  }
  return (
    <input
      {...props}
      type="search"
      value={draft.text}
      onChange={(event) => change(event.target.value)}
      onCompositionStart={() => {
        composing.current = true
        clearTimeout(timer.current)
      }}
      onCompositionEnd={(event) => {
        composing.current = false
        change(event.currentTarget.value)
      }}
      onKeyDown={(event) => {
        if (composing.current || event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229)
          return
        if (event.key === 'Enter') {
          event.preventDefault()
          publish(event.currentTarget.value)
        } else if (event.key === 'Escape') {
          event.preventDefault()
          change('')
        }
      }}
    />
  )
}
