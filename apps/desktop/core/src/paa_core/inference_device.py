"""Local hardware labels and usable inference backends; no model downloads."""
from functools import lru_cache
import ctypes
import json
import platform
import subprocess
import sys

from .repository import DomainError


def command(args):
    result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5,
                            creationflags=0x08000000 if sys.platform == 'win32' else 0)
    if result.returncode:
        raise OSError('Hardware query failed')
    return result.stdout.strip()


@lru_cache(maxsize=1)
def hardware():
    cpu = platform.processor() or platform.machine() or '处理器'
    names = []
    if sys.platform == 'darwin':
        try:
            cpu = command(['/usr/sbin/sysctl', '-n', 'machdep.cpu.brand_string']) or cpu
            displays = json.loads(command(['/usr/sbin/system_profiler', 'SPDisplaysDataType', '-json']))
            names = [row.get('sppci_model') or row.get('_name') for row in displays.get('SPDisplaysDataType', [])]
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    elif sys.platform == 'win32':
        try:
            info = json.loads(command(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; @{cpu=@(Get-CimInstance Win32_Processor | ForEach-Object {$_.Name}); gpu=@(Get-CimInstance Win32_VideoController | ForEach-Object {$_.Name})} | ConvertTo-Json -Compress"]))
            cpu = ' / '.join(info.get('cpu', [])) or cpu
            names = info.get('gpu', [])
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    result = {'cpuName': cpu.strip(), 'gpuNames': [str(name).strip() for name in names if name],
              'gpuAvailable': False, 'gpuBackend': None, 'gpuName': None,
              'gpuReason': '当前设备没有可用的 GPU 推理支持。'}
    if sys.platform == 'darwin' and platform.machine() == 'arm64':
        try:
            import mlx.core as mx
            if not mx.metal.is_available():
                raise RuntimeError('Metal unavailable')
            with mx.stream(mx.gpu):
                mx.eval(mx.ones((1,)) + 1)
            result.update(gpuAvailable=True, gpuBackend='mlx',
                          gpuName=result['gpuNames'][0] if result['gpuNames'] else cpu, gpuReason=None)
        except Exception:
            result['gpuReason'] = 'Apple GPU 推理组件不可用，请更新应用；仍可使用 CPU。'
    elif sys.platform == 'win32':
        try:
            import ctranslate2
            if not ctranslate2.get_cuda_device_count():
                raise RuntimeError('CUDA unavailable')
            if 'float16' not in ctranslate2.get_supported_compute_types('cuda'):
                raise RuntimeError('FP16 unavailable')
            # CUDA detection alone does not prove the Whisper libraries can load.
            ctypes.WinDLL('cublas64_12.dll')
            ctypes.WinDLL('cudnn64_9.dll')
            try:
                name = command(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader']).splitlines()[0]
            except (OSError, IndexError, subprocess.SubprocessError):
                name = next((name for name in result['gpuNames'] if 'nvidia' in name.lower()), 'NVIDIA GPU')
            result.update(gpuAvailable=True, gpuBackend='cuda', gpuName=name, gpuReason=None)
        except Exception:
            result['gpuReason'] = 'GPU 推理需要兼容的 NVIDIA 显卡、驱动、CUDA 12 和 cuDNN 9；AMD／Intel 显卡暂不支持。'
    return result


def apply_device(config, device, info=None):
    info = hardware() if info is None else info
    if device not in ('cpu', 'gpu'):
        raise DomainError('invalid_device', '请选择 CPU 或 GPU。')
    if device == 'gpu' and not info['gpuAvailable']:
        raise DomainError('gpu_unavailable', info['gpuReason'])
    backend = info['gpuBackend'] if device == 'gpu' else 'cpu'
    return {**config, 'version': 3, 'device': device, 'backend': backend,
            'computeType': 'int8' if device == 'cpu' else 'float16',
            'beamSize': 1 if backend == 'mlx' else 5}
