"""Durable execution identity and publication fence around an untrusted runner."""
import asyncio
import time
from sqlalchemy import select
from app.core.digests import digest
from app.core.errors import problem
from app.integrations.sandbox.client import SandboxClient
from app.modules.deliverables.service import save
from app.modules.deliverables.serializers import detail
from app.modules.executions.files import prepare_inputs, persist_file, validate_metadata
from app.modules.executions.sources import check_sources, task_sources
from app.modules.executions.models import SandboxExecution
from app.modules.messages.models import Message
from app.security.ownership import owned
from app.tasks.lease import lease
from app.tasks.context import LostLease


async def execute(context, *, code, title, references, identifier='', revision=0, step=1):
    client = SandboxClient(context.settings)
    if not 1 <= step <= 8 or not code.strip() or len(code) > 60000 or len(references) > 12 or not title.strip() or len(title) > 200:
        problem(422, '代码、标题、输入文件数量或步骤不符合要求')
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        message = await owned(db, Message, job.target_id, actor)
        inputs, sources = await prepare_inputs(db, actor, job, message, context.settings, references)
        sources = await task_sources(db, actor, job, context, sources)
        key = digest({'job': job.id, 'code': code, 'inputs': inputs, 'sources': sources, 'title': title, 'target': identifier, 'revision': revision, 'step': step})
        row = await db.scalar(select(SandboxExecution).where(SandboxExecution.key == key).with_for_update())
        if row is None:
            row = SandboxExecution(key=key, company_id=actor.company_id, owner_id=actor.id, job_id=job.id, conversation_id=message.conversation_id,
                                   message_id=message.id, fence=job.fence, code=code, sources=sources, state='queued', result={})
            db.add(row)
        else:
            await check_sources(db, actor, row.sources)
            if row.state in ('succeeded', 'failed', 'cancelled'):
                return row.result
        owner_key = digest({'company': actor.company_id, 'owner': actor.id})
    request = {'id': key, 'owner': owner_key, 'code': code, 'inputs': inputs}
    try:
        result = await client.read(key)
        if result is None:
            result = await client.submit(request)
        deadline = min(context.node_deadline or time.time() + 180, time.time() + 180)
        previous = None
        while result['state'] in ('queued', 'running'):
            if time.time() > deadline:
                await client.cancel(key)
                raise ValueError('执行或排队超过本次时间预算，请稍后重试')
            async with context.sessions.begin() as db:
                await lease(db, context)
                row = await db.scalar(select(SandboxExecution).where(SandboxExecution.key == key))
                await check_sources(db, actor, row.sources)
                if row.state != result['state']:
                    row.state = result['state']
            if result['state'] != previous:
                from app.tasks.nodes.node_execution import active_node
                from app.tasks.nodes.node_state import execution, save as save_nodes
                node = active_node.get()
                if node:
                    async with context.sessions.begin() as db:
                        current, _ = await lease(db, context)
                        state = execution(current)
                        entry = next((x for x in state['nodes'] if x['id'] == node[0]), None)
                        if entry:
                            entry['label'] = '等待执行资源' if result['state'] == 'queued' else '运行代码与生成文件'
                            save_nodes(current, state)
                previous = result['state']
            await asyncio.sleep(.5)
            result = await client.read(key)
            if result is None:
                raise ValueError('执行回执丢失，已停止自动重放，请重新发起任务')
        clean = {'executionId': row.id, 'title': title, 'state': result['state'], 'stdout': str(result.get('stdout', ''))[:16000], 'stderr': str(result.get('stderr', ''))[:8000],
                 'exitCode': result.get('exitCode'), 'message': result.get('error', ''), 'inputFiles': [item['name'] for item in inputs],
                 'inputRefs': references}
        outputs = result.get('files', [])
        if len(outputs) > 12 or sum(validate_metadata(item)['size'] for item in outputs) > 32 * 1024 * 1024:
            raise ValueError('生成文件超过导出限制')
        clean['fileChecks'] = [{'name': item['name'], 'formatReadable': True,
                               'fontCheck': '中文字体嵌入已检查；PDF标准字体无需嵌入' if item['mimeType'] == 'application/pdf' else '未检查字体嵌入，不可声称已嵌入',
                               'layoutCheck': '以本次代码实际渲染结果为准，不由格式校验保证'} for item in outputs]
        payloads = [(item, await client.file(key, item)) for item in outputs] if result['state'] == 'succeeded' else []
        async with context.sessions.begin() as db:
            job, actor = await lease(db, context)
            message = await owned(db, Message, job.target_id, actor)
            row = await db.scalar(select(SandboxExecution).where(SandboxExecution.key == key).with_for_update())
            await check_sources(db, actor, row.sources)
            if row.result.get('delivery'):
                return row.result
            if payloads:
                row.sources = await task_sources(db, actor, job, context, row.sources)
                from app.modules.executions.quota import reserve
                await reserve(db, context.settings, actor, sum(len(data) for _, data in payloads))
                files = [persist_file(context.settings, key, item, data, row.sources) for item, data in payloads]
                read_revision = context.deliverable_reads.get(identifier, job.result.get('deliverableReads', {}).get(identifier))
                item, record = await save(db, actor, message, job, {'title': title, 'body': '已生成可下载文件。'}, identifier=identifier,
                    expected_revision=revision, read_revision=read_revision, step=step, files=files)
                clean['delivery'] = await detail(db, actor, item, record)
                context.deliverable_reads[item.id] = record.revision
                job.result = {**job.result, 'deliverableReads': {**job.result.get('deliverableReads', {}), item.id: record.revision}}
            row.state, row.fence, row.result = result['state'], job.fence, clean
        await client.best_effort('release', key)
        return clean
    except (asyncio.CancelledError, LostLease):
        await asyncio.shield(client.best_effort('release', key))
        raise
