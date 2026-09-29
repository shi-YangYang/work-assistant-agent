"""Opt-in real gVisor + real database recovery, never part of default CI."""
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import pytest
from sqlalchemy import select, func
from app.integrations.models.transport import ProviderError
from app.integrations.sandbox.client import SandboxClient
from app.modules.executions.service import execute
from app.modules.executions.models import SandboxExecution
from app.modules.deliverables.models import DeliverableRevision
from app.tasks.context import LostLease
from app.tasks.models import Job
from test_business_actions import runtime

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.environ.get('SPEC042_SANDBOX_TEST') != '1', reason='Requires isolated real gVisor control')]


def enable(context):
    url = os.environ['SANDBOX_TEST_URL']
    if not url.startswith('http://127.0.0.1:'):
        raise RuntimeError('Only isolated local execution service is allowed')
    context.settings = replace(context.settings, sandbox_url=url, sandbox_token=os.environ['SANDBOX_TEST_TOKEN'])
    return SandboxClient(context.settings)


async def test_real_submission_response_loss_queries_receipt_before_retry(setup, monkeypatch):
    context, _ = await runtime(setup, '生成私人成果')
    client = enable(context)
    original = SandboxClient.submit
    calls = []
    async def lose(self, body):
        calls.append(body['id'])
        await original(self, body)
        raise ProviderError('network', 'Isolated test drops the accepted response')
    monkeypatch.setattr(SandboxClient, 'submit', lose)
    args = dict(code="from pathlib import Path\nimport time;time.sleep(1)\nPath('/work/output/结果.txt').write_text('once')", title='丢响应恢复', references=[])
    with pytest.raises(ProviderError):
        await execute(context, **args)
    accepted = await client.read(calls[0])
    monkeypatch.setattr(SandboxClient, 'submit', original)
    result = await execute(context, **args)
    assert result['state'] == 'succeeded' and len(calls) == 1
    retained = await client.read(calls[0])
    assert retained['createdAt'] == accepted['createdAt'] and retained['released']
    response = await setup[3]['employee'].get(result['delivery']['files'][0]['url'])
    assert response.content == b'once'
    async with context.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(SandboxExecution)) == 1


async def test_real_export_lease_loss_cannot_publish(setup, monkeypatch):
    context, _ = await runtime(setup, '生成文件后取消')
    enable(context)
    original = SandboxClient.file
    async def cancel_after_bytes(self, key, metadata):
        data = await original(self, key, metadata)
        async with context.sessions.begin() as db:
            job = await db.get(Job, context.job_id)
            job.state, job.fence = 'cancelled', job.fence + 1
        return data
    monkeypatch.setattr(SandboxClient, 'file', cancel_after_bytes)
    with pytest.raises(LostLease):
        await execute(context, code="from pathlib import Path\nPath('/work/output/no.txt').write_text('must not publish')", title='取消', references=[])
    async with context.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(DeliverableRevision)) == 0


async def test_real_worker_process_death_reclaims_execution(setup, tmp_path):
    context, _ = await runtime(setup, '处理中退出 worker')
    client = enable(context)
    payload = {'owner': context.owner_id, 'company': context.company_id, 'job': context.job_id, 'fence': context.fence,
               'database': context.settings.database_url, 'media': str(context.settings.media_dir),
               'url': context.settings.sandbox_url, 'token': context.settings.sandbox_token}
    path = tmp_path / 'worker.json'; path.write_text(json.dumps(payload)); path.chmod(0o600)
    process = await asyncio.create_subprocess_exec(sys.executable, str(Path(__file__).with_name('sandbox_worker_probe.py')), str(path),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    try:
        async with asyncio.timeout(20):
            while True:
                assert process.returncode is None, 'Test worker stopped before execution'
                async with context.sessions() as db:
                    execution = await db.scalar(select(SandboxExecution).where(SandboxExecution.job_id == context.job_id))
                if execution and execution.state == 'running': break
                await asyncio.sleep(.1)
        process.kill(); await process.wait()
        async with context.sessions.begin() as db:
            job = await db.get(Job, context.job_id)
            job.state, job.fence = 'cancelled', job.fence + 1
        from app.modules.executions.cleanup import stop_retired
        await stop_retired(context.sessions, context.settings)
        receipt = await client.read(execution.key)
        assert receipt['state'] == 'cancelled' and receipt['released'] and not receipt['files']
        async with context.sessions() as db:
            assert await db.scalar(select(func.count()).select_from(DeliverableRevision)) == 0
    finally:
        if process.returncode is None:
            process.kill(); await process.wait()
        path.unlink(missing_ok=True)
