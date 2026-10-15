// Number only collisions in this draft; identical content is still uploadable.
export function numberedFiles(files: File[], existing: File[]) {
  const limit = (value: string, length: number) => Array.from(value).slice(0, length).join('')
  const split = (name: string) => {
    const index = name.lastIndexOf('.')
    const suffix = index > 0 && index < name.length - 1 ? limit(name.slice(index), 16) : ''
    return { stem: suffix ? name.slice(0, index) : name, suffix }
  }
  const names = files.map((file) => {
    const { stem, suffix } = split(file.name)
    return limit(stem, 180 - Array.from(suffix).length) + suffix
  })
  const used = new Set(existing.map((file) => file.name))
  const reserved = new Set([...used, ...names])
  return files.map((file, index) => {
    let name = names[index]
    if (used.has(name)) {
      const { stem, suffix } = split(name)
      let number = 2
      do {
        const ending = ` (${number++})${suffix}`
        name = limit(stem, 180 - Array.from(ending).length) + ending
      } while (reserved.has(name))
    }
    used.add(name)
    reserved.add(name)
    return name === file.name
      ? file
      : new File([file], name, { type: file.type, lastModified: file.lastModified })
  })
}
