import { readFileSync, readdirSync } from 'node:fs'
import { dirname, relative, resolve } from 'node:path'
import ts from 'typescript'
import { expect, it } from 'vitest'

type Edge = { target: string; runtime: boolean; imports: string[] }
type Graph = Map<string, Edge[]>
const foundation = new Set(['api', 'components', 'hooks', 'lib', 'utils'])
const composition = new Set(['app', 'pages'])

function violations(graph: Graph) {
  const errors: string[] = []
  for (const [source, edges] of graph) {
    const layer = source.split('/')[0]
    for (const edge of edges) {
      const destination = edge.target.split('/')[0]
      if (foundation.has(layer) && ['features', 'pages', 'app'].includes(destination))
        errors.push(`${source} depends on higher layer ${edge.target}`)
      if (layer === 'features' && composition.has(destination))
        errors.push(`${source} depends on composition ${edge.target}`)
      if (layer === 'pages' && destination === 'app')
        errors.push(`${source} depends on app composition ${edge.target}`)
      if (
        source.includes('/api/') &&
        source.startsWith('features/') &&
        /\/(components|hooks)\//.test(edge.target)
      )
        errors.push(`${source} API depends on UI ${edge.target}`)
      if (
        (layer === 'utils' || source.includes('/utils/')) &&
        edge.runtime &&
        (edge.target === 'react' ||
          edge.target === 'react-router' ||
          /(^|\/)(api|hooks|components|lib)\//.test(edge.target))
      )
        errors.push(`${source} utility has stateful dependency ${edge.target}`)
      if (
        source.startsWith('features/') &&
        !source.includes('/api/') &&
        edge.target === 'api/client.ts' &&
        edge.imports.some((name) => ['api', 'write'].includes(name))
      )
        errors.push(`${source} bypasses its feature API`)
    }
  }
  const visited = new Set<string>()
  const active: string[] = []
  function visit(source: string) {
    if (active.includes(source)) {
      errors.push(
        `Runtime cycle: ${[...active.slice(active.indexOf(source)), source].join(' -> ')}`,
      )
      return
    }
    if (visited.has(source)) return
    visited.add(source)
    active.push(source)
    for (const edge of graph.get(source) ?? [])
      if (edge.runtime && graph.has(edge.target)) visit(edge.target)
    active.pop()
  }
  for (const source of graph.keys()) visit(source)
  return errors
}

function sources(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((item) => {
    const path = resolve(directory, item.name)
    return item.isDirectory()
      ? sources(path)
      : /\.(ts|tsx)$/.test(path) && !path.endsWith('.d.ts')
        ? [path]
        : []
  })
}

function sourceGraph(root: string): Graph {
  const files = sources(root)
  const known = new Set(files)
  const graph: Graph = new Map()
  const key = (path: string) => relative(root, path).replaceAll('\\', '/')
  for (const path of files) {
    const edges: Edge[] = []
    const file = ts.createSourceFile(path, readFileSync(path, 'utf8'), ts.ScriptTarget.Latest, true)
    function add(specifier: string, runtime: boolean, imports: string[] = []) {
      const local = specifier.startsWith('@web/')
        ? resolve(root, specifier.slice(5))
        : specifier.startsWith('.')
          ? resolve(dirname(path), specifier)
          : null
      const resolved =
        local &&
        [
          local,
          local + '.ts',
          local + '.tsx',
          resolve(local, 'index.ts'),
          resolve(local, 'index.tsx'),
        ].find((candidate) => known.has(candidate))
      edges.push({ target: resolved ? key(resolved) : specifier, runtime, imports })
    }
    function visit(node: ts.Node) {
      if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
        const clause = node.importClause
        const bindings = clause?.namedBindings
        const named = bindings && ts.isNamedImports(bindings) ? bindings.elements : []
        const runtime =
          !clause?.isTypeOnly &&
          (!clause ||
            !!clause.name ||
            (!!bindings &&
              (ts.isNamespaceImport(bindings) || named.some((item) => !item.isTypeOnly))))
        add(
          node.moduleSpecifier.text,
          runtime,
          named.map((item) => item.propertyName?.text ?? item.name.text),
        )
      } else if (
        ts.isExportDeclaration(node) &&
        node.moduleSpecifier &&
        ts.isStringLiteral(node.moduleSpecifier)
      ) {
        add(node.moduleSpecifier.text, !node.isTypeOnly)
      } else if (
        ts.isCallExpression(node) &&
        node.expression.kind === ts.SyntaxKind.ImportKeyword &&
        ts.isStringLiteral(node.arguments[0])
      ) {
        add(node.arguments[0].text, true)
      }
      ts.forEachChild(node, visit)
    }
    visit(file)
    graph.set(key(path), edges)
  }
  return graph
}

it('keeps Web foundation, feature APIs and application composition acyclic and directional', () => {
  const graph = sourceGraph(resolve(import.meta.dirname, '../../apps/web/src'))
  expect(graph.size).toBeGreaterThan(50)
  expect(violations(graph)).toEqual([])
})

it('rejects reverse dependencies, direct UI requests and runtime cycles while allowing DTO types', () => {
  const graph: Graph = new Map([
    ['lib/session.ts', [{ target: 'features/chat/types.ts', runtime: false, imports: [] }]],
    [
      'features/chat/components/Chat.tsx',
      [{ target: 'api/client.ts', runtime: true, imports: ['write'] }],
    ],
    [
      'features/chat/api/requests.ts',
      [{ target: 'features/chat/components/Chat.tsx', runtime: true, imports: [] }],
    ],
    ['utils/date.ts', [{ target: 'react', runtime: true, imports: ['useState'] }]],
    ['features/a.ts', [{ target: 'features/b.ts', runtime: true, imports: [] }]],
    ['features/b.ts', [{ target: 'features/a.ts', runtime: true, imports: [] }]],
  ])
  expect(violations(graph)).toEqual(
    expect.arrayContaining([
      expect.stringContaining('higher layer'),
      expect.stringContaining('bypasses'),
      expect.stringContaining('API depends on UI'),
      expect.stringContaining('stateful dependency'),
      expect.stringContaining('Runtime cycle'),
    ]),
  )
  expect(
    violations(
      new Map([
        ['features/a.ts', [{ target: 'features/b.ts', runtime: true, imports: [] }]],
        ['features/b.ts', [{ target: 'features/a.ts', runtime: false, imports: ['DTO'] }]],
      ]),
    ),
  ).toEqual([])
})

it('keeps CSS local to Web components and each application owns its global foundations', () => {
  const root = resolve(import.meta.dirname, '../../apps/web/src')
  const key = (path: string) => relative(root, path).replaceAll('\\', '/')
  const errors: string[] = []
  const globals = new Set(['index.css', 'theme.css', 'select.css', 'base.css'])
  function inspect(directory: string) {
    for (const item of readdirSync(directory, { withFileTypes: true })) {
      const path = resolve(directory, item.name)
      if (item.isDirectory()) {
        inspect(path)
        continue
      }
      if (!/\.(css|tsx?)$/.test(path)) continue
      const source = readFileSync(path, 'utf8')
      const name = key(path)
      if (path.endsWith('.css') && !path.endsWith('.module.css')) {
        if (dirname(path) !== resolve(root, 'styles') || !globals.has(item.name))
          errors.push(`${name} is unowned global CSS`)
      }
      if (path.endsWith('.module.css') && /(?:@value|composes:)[^;]+from\s*['"]/.test(source))
        errors.push(`${name} imports another Module's selectors`)
      const imports = [...source.matchAll(/(?:from\s*|import\s*|@import\s*)['"]([^'"]+\.css)['"]/g)]
      for (const match of imports) {
        const specifier = match[1]
        if (specifier.startsWith('@paa/') || specifier.includes('desktop'))
          errors.push(`${name} imports cross-application CSS: ${specifier}`)
        const target = specifier.startsWith('@web/')
          ? resolve(root, specifier.slice(5))
          : resolve(dirname(path), specifier)
        // Reading imports also catches missing CSS entry points before browser startup.
        readFileSync(target, 'utf8')
        if (!specifier.endsWith('.module.css')) {
          if (name !== 'main.tsx' && name !== 'styles/index.css')
            errors.push(`${name} bypasses the global CSS entry`)
          if (
            dirname(target) !== resolve(root, 'styles') ||
            !globals.has(target.split(/[\\/]/).at(-1)!)
          )
            errors.push(`${name} aggregates business CSS`)
        }
        const fromFeature = name.match(/^features\/([^/]+)\//)?.[1]
        const toFeature = key(target).match(/^features\/([^/]+)\//)?.[1]
        if (toFeature && fromFeature !== toFeature)
          errors.push(`${name} imports private feature CSS: ${key(target)}`)
      }
    }
  }
  inspect(root)
  const desktopEntry = readFileSync(resolve(root, '../../desktop/src/renderer/styles.css'), 'utf8')
  expect(desktopEntry).not.toMatch(/@paa\/ui-web\/.*\.css|apps\/web/)
  const exports = JSON.parse(
    readFileSync(resolve(root, '../../../packages/ui-web/package.json'), 'utf8'),
  ).exports
  expect(Object.keys(exports).some((name) => name.endsWith('.css'))).toBe(false)
  expect(errors).toEqual([])
})
