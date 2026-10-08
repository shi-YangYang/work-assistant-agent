"""Owned-schema publisher for browser transport timing; never calls a model."""
import asyncio
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'scripts/company/web-acceptance'))
from environment import load_environment


async def main():
    metadata, private = load_environment(sys.argv[1])
    assert metadata['suite'] == 'spec055' and metadata['purpose'] == 'web'
    os.environ.update(private['environment'])
    os.environ['PAA_REPLY_STREAM_REDIS_URL'] = 'redis://127.0.0.1:16379/0'
    os.environ['PAA_REPLY_STREAM_NAMESPACE'] = 'spec055-browser'
    from app.core.config import Settings
    from app.db import registry
    from app.db.session import database
    from app.modules.conversations.models import Conversation
    from app.modules.messages.models import Message
    from app.modules.members.models import Member
    from app.security.access import scope
    from app.tasks.models import Job
    from app.tasks.runtime.queue import claim
    from app.tasks.context import RunContext
    from app.tasks.streaming.publisher import ReplyPublisher
    from app.tasks.streaming.redis_store import close_stores

    settings = Settings()
    engine, sessions = database(settings)
    publisher = None
    try:
        async with sessions.begin() as db:
            actor = await db.get(Member, metadata['accounts']['employee']['id'])
            assert actor.company_id == metadata['accounts']['employee']['companyId']
            conversation = Conversation(company_id=actor.company_id, owner_id=actor.id, title='真实传输计时')
            db.add(conversation)
            await db.flush()
            message = Message(company_id=actor.company_id, owner_id=actor.id, conversation_id=conversation.id, text='受控传输测试，无模型调用')
            db.add(message)
            await db.flush()
            db.add(Job(company_id=actor.company_id, owner_id=actor.id, kind='message', target_id=message.id, access=scope(actor)))
            conversation_id = conversation.id
            owner_id = actor.id
        job = await claim(sessions, owner_id)
        assert job and job.target_id == message.id
        context = RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, settings, attempt=job.attempt)
        context.source_revision = message.transcript_revision
        publisher = ReplyPublisher(context, 'controlled-browser')
        await publisher.start()
        print(json.dumps({'ready': True, 'conversationId': conversation_id}), flush=True)
        assert await asyncio.to_thread(sys.stdin.readline) == 'publish\n'
        started = time.time_ns() / 1_000_000
        await publisher.write('真实通道首段正文。')
        await publisher.drain()
        print(json.dumps({'candidateEpochMs': started}), flush=True)
        await asyncio.to_thread(sys.stdin.readline)
    finally:
        if publisher:
            await publisher.close()
        await close_stores()
        await engine.dispose()


asyncio.run(main())
