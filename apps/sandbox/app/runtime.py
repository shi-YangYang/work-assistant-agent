"""Control Docker; never execute generated Python in this process or host."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from uuid import uuid4
from .files import export_archive
from .schemas import MAX_OUTPUT_BYTES


class Runtime:
    def __init__(self):
        self.image = os.environ.get('SANDBOX_IMAGE', 'noria-sandbox-runner:local')
        self.runtime = 'runsc'
        self.validation_slot = asyncio.Semaphore(1)
        self.memory = int(os.environ.get('SANDBOX_MEMORY_MIB', '1024'))
        self.cpu = float(os.environ.get('SANDBOX_CPUS', '1'))
        self.seconds = int(os.environ.get('SANDBOX_TIMEOUT_SECONDS', '60'))
        if not 128 <= self.memory <= 4096 or not .1 <= self.cpu <= 4 or not 1 <= self.seconds <= 120:
            raise ValueError('Invalid sandbox resource budget')

    async def command(self, *args, payload=None, limit=65536, timeout=30, check=True):
        process = await asyncio.create_subprocess_exec('docker', *args, stdin=asyncio.subprocess.PIPE if payload is not None else asyncio.subprocess.DEVNULL,
                                                       stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        async def read(stream):
            chunks, size = [], 0
            while chunk := await stream.read(16384):
                size += len(chunk)
                if size > limit:
                    raise ValueError('Execution output exceeds limit')
                chunks.append(chunk)
            return b''.join(chunks)
        async def send():
            if payload is not None:
                try:
                    process.stdin.write(payload)
                    await process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    process.stdin.close()
        try:
            async with asyncio.timeout(timeout):
                out, err, _, code = await asyncio.gather(read(process.stdout), read(process.stderr), send(), process.wait())
            if check and code:
                raise RuntimeError('Sandbox runtime command failed')
            return code, out, err
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()

    async def validate_file(self, path, suffix):
        # Fixed parser code is bounded separately from the control service. It
        # receives only one file on stdin, no tokens, Docker environment or path.
        async with self.validation_slot:
            process = await asyncio.create_subprocess_exec(sys.executable, '-m', __package__ + '.validator', suffix,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
                env={'PATH': os.defpath, 'PYTHONPATH': str(Path(__file__).resolve().parents[1]), 'LANG': 'C.UTF-8', 'OPENBLAS_NUM_THREADS': '1'})
            try:
                _, error = await asyncio.wait_for(process.communicate(path.read_bytes()), 12)
                if process.returncode != 0:
                    raise ValueError('生成文件校验失败：' + error.decode(errors='replace')[:240])
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()

    async def check(self):
        _, data, _ = await self.command('info', '--format', '{{json .Runtimes}}')
        if self.runtime not in json.loads(data):
            raise RuntimeError('gVisor runsc runtime is required; code execution remains disabled')
        await self.command('image', 'inspect', self.image)

    async def verify(self):
        from .schemas import ExecutionRequest
        import hashlib
        request = ExecutionRequest(id=hashlib.sha256(uuid4().bytes).hexdigest(), owner='0' * 64,
            code="import os; assert os.uname().release.endswith('gvisor'); assert os.getuid()==65532; print('isolated')")
        with tempfile.TemporaryDirectory(prefix='noria-runtime-probe-') as temporary:
            result = await self.run(request, Path(temporary))
            if result['state'] != 'succeeded' or result['stdout'].strip() != 'isolated':
                raise RuntimeError('The configured runtime did not pass the gVisor isolation probe')

    @staticmethod
    def name(identifier):
        return 'noria-exec-' + identifier

    async def remove(self, identifier):
        await self.command('rm', '-f', self.name(identifier), check=False)

    async def run(self, request, directory):
        name = self.name(request.id)
        try:
            # Docker runtime configuration is deployment-controlled, never a tool argument.
            await self.command('create', '--name', name, '--label', 'noria.sandbox=true', '--label', 'noria.execution=' + request.id,
                '--runtime', self.runtime, '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges', '--user', '65532:65532', '--pids-limit', '64',
                '--memory', f'{self.memory}m', '--memory-swap', f'{self.memory}m', '--cpus', str(self.cpu),
                '--ulimit', 'nofile=128:128', '--ulimit', 'fsize=33554432:33554432',
                '--tmpfs', '/work:rw,nosuid,nodev,noexec,size=134217728,uid=65532,gid=65532,mode=700',
                '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=16777216,uid=65532,gid=65532,mode=700',
                '--log-driver', 'none', '--init', self.image, 'sleep', str(self.seconds + 45))
            await self.command('start', name)
            task_payload = {'inputs': [item.model_dump() for item in request.inputs]}
            task_payload.update({'task': request.task.model_dump()} if request.task is not None else {'code': request.code})
            payload = json.dumps(task_payload).encode()
            if request.task is not None:
                exists, _, _ = await self.command('exec', name, 'test', '-f', '/runner/builtin.py', check=False)
                if exists:
                    raise ValueError('执行镜像不支持内置工具，请更新沙盒镜像')
            code, out, err = await self.command('exec', '-i', name, 'python', '/runner/entrypoint.py', payload=payload, timeout=self.seconds, limit=32768, check=False)
            result = {'state': 'succeeded' if code == 0 else 'failed', 'exitCode': code,
                      'stdout': out.decode(errors='replace')[:16000], 'stderr': err.decode(errors='replace')[:8000], 'files': []}
            if code == 0:
                if request.task is not None:
                    _, raw, _ = await self.command('exec', name, 'cat', '/work/builtin-result.json', limit=65536)
                    value = json.loads(raw)
                    if not isinstance(value, dict) or set(value) != {'data', 'warnings'} or not isinstance(value['data'], dict) or not isinstance(value['warnings'], list) or len(value['warnings']) > 40 or any(not isinstance(warning, str) or len(warning) > 1000 for warning in value['warnings']):
                        raise ValueError('内置工具结果格式无效')
                    result.update(value)
                _, archive, _ = await self.command('exec', name, 'tar', '-C', '/work', '-cf', '-', 'output', limit=MAX_OUTPUT_BYTES + 1024 * 1024)
                result['files'] = export_archive(archive, directory, validate_files=False)
                for file in result['files']:
                    await self.validate_file(directory / file['id'], Path(file['name']).suffix.lower())
            return result
        finally:
            await asyncio.shield(self.remove(request.id))
