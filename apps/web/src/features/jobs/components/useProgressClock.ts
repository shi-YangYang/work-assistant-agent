import { useEffect, useState } from 'react'

function initialClock(scope: string, startedAt?: string) {
  const now = Date.now()
  const parsed = Date.parse(startedAt ?? '')
  return { scope, now, startedAt: Number.isFinite(parsed) ? Math.min(parsed, now) : now }
}

export function useProgressClock(scope: string, ticking: boolean, startedAt?: string) {
  const [clock, setClock] = useState(() => initialClock(scope, startedAt))
  // Model phases and tool rounds share one clock; only a new execution resets it.
  if (clock.scope !== scope) setClock(initialClock(scope, startedAt))
  useEffect(() => {
    if (!ticking) return
    const timer = setInterval(() => {
      const now = Date.now()
      setClock((previous) => (previous.scope === scope ? { ...previous, now } : previous))
    }, 1000)
    return () => clearInterval(timer)
  }, [scope, ticking])
  return { now: clock.now, seconds: Math.max(0, Math.floor((clock.now - clock.startedAt) / 1000)) }
}
