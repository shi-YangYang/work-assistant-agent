import { useEffect, useState } from 'react'

const storageKey = 'paa.company.pet-visible'

function savedVisibility() {
  try {
    return localStorage.getItem(storageKey) === 'true'
  } catch {
    return false
  }
}

export function usePetVisibility() {
  const [visible, setVisible] = useState(savedVisibility)
  useEffect(() => {
    const sync = (event: StorageEvent) => {
      if (event.key === storageKey || event.key === null) setVisible(savedVisibility())
    }
    window.addEventListener('storage', sync)
    return () => window.removeEventListener('storage', sync)
  }, [])

  function changeVisibility(value: boolean) {
    setVisible(value)
    try {
      localStorage.setItem(storageKey, String(value))
    } catch {
      // Keep the toggle usable for this page when browser storage is unavailable.
    }
  }

  return { visible, setVisible: changeVisibility }
}
