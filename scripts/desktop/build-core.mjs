import { delimiter, resolve } from 'node:path'
import { spawnSync } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import { pythonCommand } from '../lib/python-command.mjs'
const root = resolve(import.meta.dirname, '../..')
process.chdir(root)
const { command, args } = pythonCommand(root)
if (!(
  (process.platform === 'darwin' && process.arch === 'arm64') ||
  (process.platform === 'win32' && process.arch === 'x64')
))
  throw new Error('Build on macOS ARM64 or Windows x64 for that platform')
const modelCheck = spawnSync(
  command,
  [
    ...args,
    '-c',
    "import sys; sys.path.insert(0, 'apps/desktop/core/src'); from paa_core.speaker_worker import bundled_model_path, verified; assert verified(bundled_model_path()), 'Bundled Community-1 weights are missing or modified'",
  ],
  { stdio: 'inherit' },
)
if (modelCheck.status !== 0) process.exit(modelCheck.status ?? 1)
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
    'apps/desktop/core/src',
    '--add-data',
    `${resolve('apps/desktop/resources/models/speaker-community-1')}${delimiter}models/speaker-community-1`,
    '--collect-all',
    'pyannote.audio',
    '--collect-all',
    'pyannote.pipeline',
    '--collect-all',
    'torchaudio',
    '--collect-all',
    'torchcodec',
    '--collect-all',
    'lightning',
    '--collect-all',
    'pytorch_lightning',
    '--recursive-copy-metadata',
    'pyannote-audio',
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
    ...(process.platform === 'darwin'
      ? [
          '--collect-all',
          'mlx',
          '--collect-all',
          'mlx_whisper',
          '--collect-all',
          'tiktoken_ext',
          '--recursive-copy-metadata',
          'mlx-whisper',
        ]
      : []),
    '--exclude-module',
    'tkinter',
    '--exclude-module',
    'pytest',
    'apps/desktop/core/src/paa_core/__main__.py',
  ],
  { stdio: 'inherit' },
)
if (result.status !== 0) process.exit(result.status ?? 1)
const notices = spawnSync(command, [...args, 'scripts/desktop/core-licenses.py'], {
  stdio: 'inherit',
})
process.exit(notices.status ?? 1)
