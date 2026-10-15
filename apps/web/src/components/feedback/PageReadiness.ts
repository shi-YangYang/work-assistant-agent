import { createContext, useContext, useLayoutEffect } from 'react'

export const PageReadyContext = createContext<((ready: boolean) => void) | null>(null)

export function usePageReady(ready?: boolean) {
  const report = useContext(PageReadyContext)
  useLayoutEffect(() => {
    // An undefined state delegates readiness to the next mounted loading stage.
    if (ready !== undefined) report?.(ready)
  }, [ready, report])
  return report !== null
}
