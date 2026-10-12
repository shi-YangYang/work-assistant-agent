"""Shared controlled fixtures extracted from test_documents."""
from datetime import timedelta
from _support.materials.document_samples import samples
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from app.db.base import now
from app.modules.attachments.documents import DOCUMENT_TYPES
from app.tasks.context import RunContext
from app.tasks.processing.handlers import process_job
from app.tasks.models import Job


async def upload(client, name='演示项目.txt', data=None, mime=None):
    response = await client.post('/api/v1/uploads', files={'file': (name, samples()[name] if data is None else data, mime or DOCUMENT_TYPES.get('.' + name.split('.')[-1], 'application/octet-stream'))})
    assert response.status_code == 201, response.text
    return response.json()


async def run(settings, sessions, users, sent, model=None):
    async with sessions.begin() as db:
        job = await db.get(Job, sent['jobId'])
        job.state, job.fence, job.lease_until = 'running', job.fence + 1, now() + timedelta(seconds=90)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(job, sessions, settings, saver, model=model)
    return job


async def running_context(settings, sessions, actor, sent):
    async with sessions.begin() as db:
        job = await db.get(Job, sent['jobId'])
        job.state, job.fence, job.lease_until = 'running', job.fence + 1, now() + timedelta(seconds=90)
    return RunContext(actor.id, actor.company_id, job.id, job.fence, sessions, settings)
