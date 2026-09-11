import { spawnSync } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import { pythonCommand } from './python-command.mjs'
const { command, args } = pythonCommand(process.cwd())
if (!(
  (process.platform === 'darwin' && process.arch === 'arm64') ||
  (process.platform === 'win32' && process.arch === 'x64')
))
  throw new Error('Build on macOS ARM64 or Windows x64 for that platform')
mkdirSync('build/core', { recursive: true })
const result = spawnSync(
  command,
  [
    ...args,
    '-m',
    'PyInstaller',
    '--noconfirm',
    '--onedir',
    '--console',
    '--noupx',
    '--name',
    'paa-core',
    '--distpath',
    'dist/core',
    '--workpath',
    'build/core/work',
    '--specpath',
    'build/core',
    '--paths',
    'src/python',
    '--collect-all',
    'faster_whisper',
    '--collect-all',
    'ctranslate2',
    '--collect-all',
    'onnxruntime',
    '--collect-all',
    'av',
    '--collect-all',
    'tokenizers',
    '--collect-all',
    '_sounddevice_data',
    '--collect-data',
    'certifi',
    '--recursive-copy-metadata',
    'faster-whisper',
    '--copy-metadata',
    'sounddevice',
    '--copy-metadata',
    'httpx',
    '--exclude-module',
    'tkinter',
    '--exclude-module',
    'pytest',
    'src/python/paa_core/__main__.py',
  ],
  { stdio: 'inherit' },
)
if (result.status !== 0) process.exit(result.status ?? 1)
const notices = spawnSync(command, [...args, 'scripts/core-licenses.py'], { stdio: 'inherit' })
process.exit(notices.status ?? 1)
