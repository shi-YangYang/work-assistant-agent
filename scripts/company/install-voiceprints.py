"""Prepare optional, isolated CPU enrollment inference without changing API dependencies."""
from pathlib import Path
import subprocess
import sys
import venv

root = Path(__file__).resolve().parents[2]
if sys.version_info[:2] != (3, 12):
    raise SystemExit('请使用 Python 3.12 安装公司声纹组件')
environment = root / '.venv-voiceprints'
venv.EnvBuilder(with_pip=True).create(environment)
python = environment / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
command = [str(python), '-m', 'pip', 'install', 'torch==2.11.0', 'torchaudio==2.11.0']
if sys.platform in ('linux', 'win32'):
    command += ['--index-url', 'https://download.pytorch.org/whl/cpu']
subprocess.run(command, cwd=root, check=True)
subprocess.run([str(python), '-m', 'pip', 'install', str(root / 'packages/voiceprint-engine') + '[runtime]'], cwd=root, check=True)
subprocess.run([str(python), '-c', 'import sys; from paa_voiceprints import model_file; model_file(sys.argv[1]); print("公司声纹运行环境与固定模型已就绪")', str(root / 'apps/desktop/resources/models/speaker-community-1/embedding/pytorch_model.bin')], cwd=root, check=True)
