import asyncio
from dataclasses import replace
from pathlib import Path
import sys
import os
from uuid import uuid4

import httpx
import pytest_asyncio
from pwdlib import PasswordHash
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import delete, text

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/python'))
from paa_server.api import create_app
from paa_server.config import Settings
from paa_server.db import database
from paa_server.models import Base, Company, Member
from paa_server.model_secrets import initialize_key


@pytest_asyncio.fixture
async def setup(tmp_path):
    base = Settings()
    test_url = os.getenv('DATABASE_TEST_URL')
    if not test_url:
        raise RuntimeError('Set DATABASE_TEST_URL to a dedicated migrated PostgreSQL test database')
    settings = replace(base, database_url=test_url.replace('postgresql://', 'postgresql+psycopg://', 1), media_dir=tmp_path / 'media', cookie_secure=False, web_origin='http://test', agent_base_url='', agent_key='', asr_base_url='', asr_key='', model_key_file=tmp_path / 'master.key')
    initialize_key(settings.model_key_file)
    engine, sessions = database(settings)
    company_ids, users = [], {}
    hashed = PasswordHash.recommended().hash('controlled-test-password')
    async with sessions.begin() as db:
        for name in ('primary', 'other'):
            company = Company(name='受控测试公司 ' + uuid4().hex[:8], environment_models=name == 'primary')
            db.add(company); await db.flush(); company_ids.append(company.id)
            for role in (('admin', 'employee', 'peer') if name == 'primary' else ('outsider',)):
                member = Member(company_id=company.id, username='test_' + uuid4().hex[:14], name='受控测试 ' + role, role='admin' if role == 'admin' else 'employee', password_hash=hashed, must_change_password=False)
                db.add(member); await db.flush(); users[role] = member
    app = create_app(settings)
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    clients = {}
    for key, member in users.items():
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'Origin': 'http://test'})
        response = await client.post('/api/v1/auth/login', json={'username': member.username, 'password': 'controlled-test-password'})
        assert response.status_code == 200, response.text
        client.headers['X-CSRF-Token'] = response.json()['csrf']
        clients[key] = client
    yield settings, sessions, users, clients
    for client in clients.values():
        await client.aclose()
    await lifespan.__aexit__(None, None, None)
    # A message job may retain several input-version checkpoint threads. Only
    # remove this fixture's companies, including failure paths in a regression.
    async with sessions() as db:
        threads = []
        for company_id in company_ids:
            threads.extend((await db.scalars(text('SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE :prefix'), {'prefix': company_id + ':%'})).all())
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
        for thread in threads:
            await saver.adelete_thread(thread)
    async with sessions.begin() as db:
        from paa_server.models import Session
        await db.execute(delete(Session).where(Session.member_id.in_([u.id for u in users.values()])))
        for table in reversed(Base.metadata.sorted_tables):
            if 'company_id' in table.c:
                await db.execute(table.delete().where(table.c.company_id.in_(company_ids)))
        await db.execute(delete(Company).where(Company.id.in_(company_ids)))
    await engine.dispose()
