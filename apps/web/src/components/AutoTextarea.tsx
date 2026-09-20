import type { RefObject, TextareaHTMLAttributes } from 'react'
import { useLayoutEffect, useRef } from 'react'

function resizeTextarea(node: HTMLTextAreaElement | null) {
  if (!node) return
  node.style.height = 'auto'
  const style = getComputedStyle(node)
  const border = parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth)
  const maximum = parseFloat(style.maxHeight) || 280
  node.style.height = `${Math.min(node.scrollHeight + border, maximum)}px`
  node.style.overflowY = node.scrollHeight + border > maximum ? 'auto' : 'hidden'
}

export function AutoTextarea({
  value,
  defaultValue,
  className = '',
  rows = 2,
  elementRef,
  onInput,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & {
  elementRef?: RefObject<HTMLTextAreaElement | null>
}) {
  const local = useRef<HTMLTextAreaElement>(null)
  const ref = elementRef ?? local
  useLayoutEffect(() => resizeTextarea(ref.current), [value, defaultValue, ref])
  useLayoutEffect(() => {
    const node = ref.current
    if (!node) return
    let width = node.clientWidth
    const observer = new ResizeObserver(() => {
      if (node.clientWidth !== width) {
        width = node.clientWidth
        resizeTextarea(node)
      }
    })
    observer.observe(node)
    return () => observer.disconnect()
  }, [ref])
  return (
    <textarea
      {...props}
      ref={ref}
      value={value}
      defaultValue={defaultValue}
      rows={rows}
      className={`auto-textarea ${className}`}
      onInput={(event) => {
        resizeTextarea(event.currentTarget)
        onInput?.(event)
      }}
    />
  )
}
