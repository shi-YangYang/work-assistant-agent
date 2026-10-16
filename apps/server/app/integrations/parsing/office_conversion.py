"""Worker-owned, bounded Office preparation; no model/sandbox requests."""
import asyncio
from functools import lru_cache
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from weakref import WeakKeyDictionary
from app.integrations.parsing.document_parser import PARSER_VERSION

_limits = WeakKeyDictionary()
log = logging.getLogger('paa.company')
MISSING = '暂时无法读取此格式，请联系管理员，或另存为 DOCX、XLSX、PPTX 后上传。'


def failure(message):
    return {'status': 'failed', 'chunks': [], 'info': {'error': message}}


def environment():
    return {'LANG': 'C.UTF-8', 'PATH': os.defpath, **({'SYSTEMROOT': os.environ['SYSTEMROOT']} if 'SYSTEMROOT' in os.environ else {})}


@lru_cache(maxsize=1)
def converter():
    candidates = [os.getenv('PAA_OFFICE_BINARY'), shutil.which('soffice'), shutil.which('libreoffice'), '/Applications/LibreOffice.app/Contents/MacOS/soffice']
    for value in candidates:
        if value and Path(value).is_file():
            try:
                result = subprocess.run([value, '--headless', '--version'], capture_output=True, timeout=5, env=environment(), check=True)
                version = result.stdout.decode(errors='replace').strip()
                if 'LibreOffice' in version:
                    return str(Path(value).absolute()), version
            except (OSError, subprocess.SubprocessError):
                continue
    return '', ''


def cleanup_abandoned():
    """Remove only owned, labelled workspaces whose two recorded owners died."""
    def alive(pid):
        if not isinstance(pid, int) or pid <= 1:
            return True
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except OSError:
            return True
    for path in Path(tempfile.gettempdir()).glob('noria-office-*'):
        try:
            if path.is_symlink() or not path.is_dir() or time.time() - path.stat().st_mtime < 60:
                continue
            if hasattr(os, 'getuid') and path.stat().st_uid != os.getuid():
                continue
            owner = json.loads((path / 'owner.json').read_text())
            if not alive(owner.get('worker')) and not alive(owner.get('supervisor')):
                shutil.rmtree(path)
        except (OSError, ValueError, TypeError):
            log.warning('office temporary_cleanup_failed')


async def office_version():
    _, version = await asyncio.to_thread(converter)
    fingerprint = hashlib.sha256((PARSER_VERSION + ':office-policy-v1:' + version).encode()).hexdigest()[:32]
    return 'office-v1:' + fingerprint


async def parse_office(path, suffix, *, timeout=60, on_stage=None, destination=None, mode="parse", start=0, sheet=""):
    executable, _ = await asyncio.to_thread(converter) if mode != 'page' else (shutil.which('pdftoppm'), '')
    if not executable:
        return failure('页面图片读取服务暂不可用' if mode == 'page' else MISSING)
    async def stage(name):
        if on_stage:
            await on_stage(name)
    await stage('queued')
    limit = _limits.setdefault(asyncio.get_running_loop(), asyncio.Semaphore(1))
    async with limit:
        process, workspace = None, None
        try:
            workspace = Path(tempfile.mkdtemp(prefix='noria-office-'))
            (workspace / 'owner.json').write_text(json.dumps({'worker': os.getpid(), 'supervisor': os.getpid()}))
            process = await asyncio.create_subprocess_exec(sys.executable, '-I', str(Path(__file__).with_name('office_process.py')), str(Path(path).absolute()), suffix, executable, str(timeout), str(workspace), json.dumps({"destination": str(destination) if destination else "", "mode": mode, "start": start, "sheet": sheet}), stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=environment(), start_new_session=os.name == 'posix')
            async def receive():
                pending, total, result = bytearray(), 0, None
                while block := await process.stdout.read(65536):
                    total += len(block)
                    if total > 2 * 1024 * 1024 + 8192:
                        return failure('文档提取结果超出限制，请拆分文件')
                    pending.extend(block)
                    while b'\n' in pending:
                        line, _, rest = pending.partition(b'\n'); pending[:] = rest
                        packet = json.loads(line)
                        if packet.get('stage') in ('queued', 'converting', 'parsing'):
                            await stage(packet['stage'])
                        if packet.get('cleanupFailed'):
                            log.warning('office temporary_cleanup_failed')
                        if 'result' in packet:
                            result = packet['result']
                await process.wait()
                if process.returncode or not isinstance(result, dict) or result.get('status') not in ('ready', 'partial', 'empty', 'failed') or not isinstance(result.get('chunks'), list) or not isinstance(result.get('info'), dict):
                    return failure('文件转换进程中断，请稍后重新解析')
                return result
            return await asyncio.wait_for(receive(), timeout + 3)
        except asyncio.TimeoutError:
            return failure('文件处理超时或超出资源限制，请拆分或重新导出后上传')
        except (OSError, ValueError):
            return failure('文件转换暂时不可用，请稍后重新解析')
        finally:
            if process:
                if process.returncode is None:
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        pass
                    try:
                        await asyncio.wait_for(process.wait(), 4)
                    except asyncio.TimeoutError:
                        pass
                # Children inherit the supervisor's group. This also runs if
                # the supervisor itself crashed/SIGKILLed before cleanup.
                if os.name == 'posix':
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                elif process.returncode is None:
                    process.kill()
                await process.wait()
            if workspace and workspace.exists():
                try:
                    await asyncio.to_thread(shutil.rmtree, workspace)
                except OSError:
                    log.warning('office temporary_cleanup_failed')
