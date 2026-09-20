export function pageParams(
  params: URLSearchParams,
  direction: 'next' | 'previous',
  cursor?: string | null,
) {
  const next = new URLSearchParams(params)
  const boundaries = next.getAll('after')
  next.delete('after')
  if (direction === 'next' && cursor) boundaries.push(cursor)
  else if (direction === 'previous') boundaries.pop()
  for (const value of boundaries) next.append('after', value)
  return next
}

export function filterParams(params: URLSearchParams, values: Record<string, string>) {
  const next = new URLSearchParams(params)
  next.delete('after')
  for (const [key, value] of Object.entries(values)) {
    if (value) next.set(key, value)
    else next.delete(key)
  }
  return next
}
