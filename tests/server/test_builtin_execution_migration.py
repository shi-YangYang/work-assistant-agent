"""Preserve historical Python receipts across the nullable builtin snapshot migration."""
import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.config import Settings
from app.db.base import now
from app.modules.conversations.models import Conversation
from app.modules.members.models import Company, Member
from app.modules.messages.models import Message
from app.tasks.models import Job


def test_builtin_snapshot_migration_preserves_python_and_round_trips_json(monkeypatch):
    Settings()
    url = make_url(os.environ['DATABASE_TEST_URL']).set(drivername='postgresql+psycopg')
    assert url.database == 'paa_company_test', 'Refusing migration tests outside the test database'
    schema = 'builtin_migration_' + uuid4().hex
    engine = create_engine(url)
    scoped_url = url.update_query_dict({'options': '-csearch_path=' + schema})
    scoped = create_engine(scoped_url)
    monkeypatch.setenv('DATABASE_URL', scoped_url.render_as_string(hide_password=False))
    config = Config()
    config.set_main_option('script_location', str(Path(__file__).resolve().parents[2] / 'apps/server/app/migrations'))
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
        command.upgrade(config, '0022_sandbox_deliverables')
        with scoped.begin() as connection:
            company_id = connection.execute(Company.__table__.insert().values(name='内置工具迁移验证').returning(Company.id)).scalar_one()
            owner_id = connection.execute(Member.__table__.insert().values(
                company_id=company_id, username='migration_' + uuid4().hex, name='原有用户',
                password_hash='unchanged-controlled-hash').returning(Member.id)).scalar_one()
            owned = {'company_id': company_id, 'owner_id': owner_id}
            conversation_id = connection.execute(Conversation.__table__.insert().values(
                **owned, title='原有会话').returning(Conversation.id)).scalar_one()
            message_id = connection.execute(Message.__table__.insert().values(
                **owned, conversation_id=conversation_id, text='原有计算').returning(Message.id)).scalar_one()
            job_id = connection.execute(Job.__table__.insert().values(
                **owned, kind='message', target_id=message_id, state='succeeded').returning(Job.id)).scalar_one()
            previous = Table('company_sandbox_execution', MetaData(), autoload_with=connection)
            old = {'id': str(uuid4()), **owned, 'created_at': now(), 'key': 'a' * 64,
                   'job_id': job_id, 'conversation_id': conversation_id, 'message_id': message_id,
                   'fence': 1, 'state': 'succeeded', 'code': "print('原有代码')", 'sources': [],
                   'result': {'stdout': '原有结果', 'exitCode': 0, 'delivery': {
                       'id': 'existing-deliverable', 'revision': 2,
                       'files': [{'id': 'existing-file', 'name': '历史.csv', 'url': '/existing/private-file'}]}}}
            connection.execute(previous.insert().values(**old))
            before = dict(connection.execute(select(previous)).mappings().one())

        command.upgrade(config, '0023_builtin_execution')
        with scoped.begin() as connection:
            assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0023_builtin_execution'
            columns = {column['name']: column for column in inspect(connection).get_columns('company_sandbox_execution')}
            assert columns['request']['nullable'] and isinstance(columns['request']['type'], JSONB)
            current = Table('company_sandbox_execution', MetaData(), autoload_with=connection)
            restored = dict(connection.execute(select(current).where(current.c.id == old['id'])).mappings().one())
            assert restored == {**before, 'request': None}
            task = {'kind': 'builtin', 'name': 'inspect_table', 'version': 1,
                    'arguments': {'source': {'input_ref': {'attachment_id': '真实附件编号'}}, 'sample_rows': 2}}
            builtin_id = str(uuid4())
            connection.execute(current.insert().values(**{**old, 'id': builtin_id, 'key': 'b' * 64,
                'code': '', 'request': task, 'result': {'data': {'rowCount': 2}, 'warnings': []}}))
            builtin = connection.execute(select(current).where(current.c.id == builtin_id)).mappings().one()
            assert builtin['request'] == task and builtin['code'] == ''

        command.downgrade(config, '0022_sandbox_deliverables')
        with scoped.connect() as connection:
            assert 'request' not in {column['name'] for column in inspect(connection).get_columns('company_sandbox_execution')}
            previous = Table('company_sandbox_execution', MetaData(), autoload_with=connection)
            assert dict(connection.execute(select(previous).where(previous.c.id == old['id'])).mappings().one()) == before
            assert connection.scalar(select(previous.c.code).where(previous.c.id == builtin_id)) == ''
    finally:
        scoped.dispose()
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()
