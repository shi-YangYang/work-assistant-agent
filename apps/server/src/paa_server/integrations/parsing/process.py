import asyncio
import json
import os
import sys
from paa_server.integrations.parsing.document_parser import MEMORY_BYTES
from pathlib import Path


async def parse_process(path, suffix, *, timeout=60, entrypoint=None, max_output=2 * 1024 * 1024):
    """No credentials/config inherited, bounded pipe, cancellation always reaps child."""
    process = await asyncio.create_subprocess_exec(sys.executable, '-I', str(entrypoint or Path(__file__).with_name('document_parser.py')), str(path), suffix, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env={'LANG': 'C.UTF-8', **({'SYSTEMROOT': os.environ['SYSTEMROOT']} if 'SYSTEMROOT' in os.environ else {})})
    memory_exceeded = False
    async def monitor_memory():
        nonlocal memory_exceeded
        if sys.platform != 'darwin':
            return
        while process.returncode is None:
            probe = await asyncio.create_subprocess_exec('/bin/ps', '-o', 'rss=', '-p', str(process.pid), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            try:
                raw, _ = await asyncio.wait_for(probe.communicate(), 2)
            finally:
                if probe.returncode is None:
                    probe.kill()
                await probe.wait()
            if raw.strip() and int(raw.strip()) * 1024 > MEMORY_BYTES:
                memory_exceeded = True
                if process.returncode is None:
                    process.kill()
                return
            await asyncio.sleep(.1)
    memory_task = asyncio.create_task(monitor_memory())
    def monitor_finished(task):
        if not task.cancelled() and task.exception() and process.returncode is None:
            process.kill()
    memory_task.add_done_callback(monitor_finished)
    async def receive():
        output = bytearray()
        while block := await process.stdout.read(65536):
            output.extend(block)
            if len(output) > max_output:
                raise ValueError('文档提取结果超出限制，请拆分文件')
        await process.wait()
        if process.returncode or memory_exceeded:
            raise ValueError('文档超出解析资源限制或解析进程中断，请拆分后重试')
        return json.loads(output)
    try:
        return await asyncio.wait_for(receive(), timeout)
    except asyncio.TimeoutError:
        return {'status': 'failed', 'chunks': [], 'info': {'error': '文档解析超过 60 秒，请拆分文件后重试'}}
    except (ValueError, OSError) as error:
        return {'status': 'failed', 'chunks': [], 'info': {'error': str(error) if isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError) else '解析进程未返回有效结果，请重试'}}
    finally:
        memory_task.cancel()
        await asyncio.gather(memory_task, return_exceptions=True)
        if process.returncode is None:
            process.kill()
        await process.wait()
