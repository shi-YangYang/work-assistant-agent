export function deliverablePath(id: string, revision: number) {
  return `/deliverables/${encodeURIComponent(id)}?revision=${revision}`
}
