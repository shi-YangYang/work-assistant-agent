export const STORAGE = 'paa.desktop.authorization'

export function clearDesktopRequest() {
  sessionStorage.removeItem(STORAGE)
}
