import { execFileSync, spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import {
  constants,
  cpSync,
  existsSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const desktop = fileURLToPath(new URL('../../apps/desktop/', import.meta.url))
const require = createRequire(join(desktop, 'package.json'))
const env = { ...process.env }

if (process.platform === 'darwin') {
  const executable = require('electron')
  const { version } = require('electron/package.json')
  const { productName } = JSON.parse(readFileSync(join(desktop, 'electron-builder.json'), 'utf8'))
  const cache = fileURLToPath(
    new URL(`../../node_modules/.cache/paa-electron/${version}-${process.arch}/`, import.meta.url),
  )
  const bundle = join(cache, `${productName}.app`)
  const marker = join(cache, 'prepared')
  const identity = `${productName}:${createHash('sha256').update(readFileSync(executable)).digest('hex')}`
  const target = join(bundle, 'Contents/MacOS/Electron')
  if (!existsSync(target) || !existsSync(marker) || readFileSync(marker, 'utf8') !== identity) {
    mkdirSync(cache, { recursive: true })
    rmSync(bundle, { recursive: true, force: true })
    cpSync(dirname(dirname(dirname(executable))), bundle, {
      recursive: true,
      verbatimSymlinks: true,
      mode: constants.COPYFILE_FICLONE,
    })
    // Electron's development executable has an unbound plist. Preserve its original
    // signature and keychain identity: never re-sign or modify the executable.
    const plist = join(bundle, 'Contents/Info.plist')
    for (const key of ['CFBundleName', 'CFBundleDisplayName'])
      execFileSync('/usr/bin/plutil', ['-replace', key, '-string', productName, plist])
    writeFileSync(marker, identity)
  }
  env.ELECTRON_EXEC_PATH = target
}

const cli = join(dirname(require.resolve('electron-vite/package.json')), 'bin/electron-vite.js')
const child = spawn(process.execPath, [cli, ...process.argv.slice(2)], {
  cwd: desktop,
  env,
  stdio: 'inherit',
})
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal))
child.on('error', (error) => {
  console.error(error.message)
  process.exit(1)
})
child.on('exit', (code) => process.exit(code ?? 1))
