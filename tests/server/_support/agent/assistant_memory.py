"""Shared controlled fixtures extracted from test_assistant_memory."""
from app.modules.memories import service
from app.tasks.context import RunContext
from app.tasks.lease import lease
from app.tasks.runtime.queue import claim
from _support.http.company import send


PATH = '/api/v1/assistant/memory'


async def context_for(setup, text='以后先给结论，少用表格'):
    settings, sessions, users, clients = setup
    sent = await send(clients['employee'], text)
    job = await claim(sessions, users['employee'].id)
    context = RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, settings, source_revision=0)
    from app.agent.memory.middleware import prepare
    await prepare(context)
    return context, sent


async def apply(context, **kwargs):
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        return await service.change(db, actor, job, context.memory_snapshot, call_id=kwargs.pop('call_id', 'call'), **kwargs)
