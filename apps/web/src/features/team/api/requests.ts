export function teamWorkspacePath(view: 'reports' | 'work', query: URLSearchParams) {
  return `/team/workspace/${view}?${query}`
}
