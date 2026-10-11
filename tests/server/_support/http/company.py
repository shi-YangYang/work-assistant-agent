"""Shared controlled fixtures extracted from test_company."""
from datetime import timedelta
from _support.agent.fakes import controlled_model
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from app.db.base import now
from app.tasks.processing.handlers import process_job
from app.tasks.models import Job
from uuid import uuid4


def keyed():
    return {'Idempotency-Key': str(uuid4())}


async def send(client, text='初稿完成，等待报价', attachments=None):
    response = await client.post('/api/v1/messages', json={'text': text, 'attachmentIds': attachments or []}, headers=keyed())
    assert response.status_code == 202, response.text
    return response.json()


async def run_target(settings, sessions, users, result, scenario='progress'):
    # Claim only the test job, leaving user-created dev jobs untouched.
    async with sessions.begin() as db:
        job = await db.get(Job, result['jobId'])
        job.state, job.fence, job.lease_until = 'running', job.fence + 1, now() + timedelta(seconds=90)
    model = controlled_model(scenario)
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        await process_job(job, sessions, settings, saver, model=model)
    return model
