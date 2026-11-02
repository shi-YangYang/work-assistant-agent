import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'apps/server'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'packages/voiceprint-engine/src'))

import httpx
import os
import pytest
import pytest_asyncio
from dataclasses import replace
from fastapi import Response
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from app.main import create_app
from app.core.config import Settings
from app.db.base import Base
from app.db.session import database
from app.modules.auth.sessions import issue_session
from app.modules.members.models import Company, Member
from app.security.secrets import initialize_key
from pwdlib import PasswordHash
from sqlalchemy import delete, select, text
from sqlalchemy.engine import make_url
from uuid import uuid4




@pytest.fixture(scope='session')
def member_password_hash():
    # Reuse only the immutable hash; accounts and sessions stay isolated per test.
    return PasswordHash.recommended().hash('controlled-test-password')


@pytest_asyncio.fixture
async def setup(tmp_path, member_password_hash):
    base = Settings()
    test_url = os.getenv('DATABASE_TEST_URL')
    if not test_url:
        raise RuntimeError('Set DATABASE_TEST_URL to a dedicated migrated PostgreSQL test database')
    if make_url(test_url).database != 'paa_company_test':
        raise RuntimeError('Refusing tests outside the dedicated paa_company_test database')
    settings = replace(base, database_url=test_url.replace('postgresql://', 'postgresql+psycopg://', 1), media_dir=tmp_path / 'media', cookie_secure=False, web_origin='http://test', agent_base_url='', agent_key='', asr_base_url='', asr_key='', sandbox_url='', sandbox_token='', model_key_file=tmp_path / 'master.key')
    initialize_key(settings.model_key_file)
    engine, sessions = database(settings)
    company_ids, users = [], {}
    async with sessions.begin() as db:
        for name in ('primary', 'other'):
            company = Company(name='受控测试公司 ' + uuid4().hex[:8], environment_models=name == 'primary')
            db.add(company); await db.flush(); company_ids.append(company.id)
            for role in (('admin', 'employee', 'peer') if name == 'primary' else ('outsider',)):
                # Existing-account scenarios use an explicit saved preference.
                # New-account defaults are exercised through creation/migration tests.
                member = Member(company_id=company.id, username='test_' + uuid4().hex[:14], name='受控测试 ' + role, role='admin' if role == 'admin' else 'employee', password_hash=member_password_hash, execution_mode='auto')
                db.add(member); await db.flush(); users[role] = member
    app = create_app(settings)
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    clients = {}
    # Business tests need authenticated sessions, not four password logins per
    # case. Use real session issuance/cookies; HTTP authentication, CSRF and
    # tenant checks remain active. Auth tests still call the real login endpoint.
    async with sessions.begin() as db:
        for key, member in users.items():
            client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers={'Origin': 'http://test'})
            response = Response()
            client.headers['X-CSRF-Token'] = issue_session(db, member, response, settings)
            client.cookies.extract_cookies(httpx.Response(200, headers=response.headers, request=httpx.Request('POST', 'http://test/api/v1/auth/login')))
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
        from app.modules.auth.models import Session
        await db.execute(delete(Session).where(Session.member_id.in_(select(Member.id).where(Member.company_id.in_(company_ids)))))
        for table in reversed(Base.metadata.sorted_tables):
            if 'company_id' in table.c:
                await db.execute(table.delete().where(table.c.company_id.in_(company_ids)))
        await db.execute(delete(Company).where(Company.id.in_(company_ids)))
    await engine.dispose()
