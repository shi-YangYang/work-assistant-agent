"""Account preference migration preserves tasks without expanding old approvals."""
import os
from pathlib import Path
from uuid import uuid4
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema
from app.core.config import Settings
from app.modules.members.models import Company, Member
from app.modules.conversations.models import Conversation
from app.tasks.models import Job


def test_execution_settings_migration_preserves_records_and_can_downgrade(monkeypatch):
    Settings()
    url = make_url(os.environ['DATABASE_TEST_URL']).set(drivername='postgresql+psycopg')
    assert url.database == 'paa_company_test'
    schema = 'execution_migration_' + uuid4().hex
    engine = create_engine(url)
    scoped_url = url.update_query_dict({'options': '-csearch_path=' + schema})
    scoped = create_engine(scoped_url)
    monkeypatch.setenv('DATABASE_URL', scoped_url.render_as_string(hide_password=False))
    config = Config()
    config.set_main_option('script_location', str(Path(__file__).resolve().parents[4] / 'apps/server/app/migrations'))
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
        command.upgrade(config, '0023_builtin_execution')
        with scoped.begin() as connection:
            company = connection.execute(Company.__table__.insert().values(name='执行权限迁移').returning(Company.id)).scalar_one()
            old_conversations = Table('company_conversation', MetaData(), autoload_with=connection)
            owners = {}
            for mode in ('ask', 'auto', 'full'):
                owner = connection.execute(Member.__table__.insert().values(company_id=company, username=mode, name=mode).returning(Member.id)).scalar_one()
                owners[mode] = owner
                conversation = connection.execute(Conversation.__table__.insert().values(company_id=company, owner_id=owner, title=mode).returning(Conversation.id)).scalar_one()
                connection.execute(old_conversations.update().where(old_conversations.c.id == conversation).values(execution_mode=mode, full_access_confirmed=mode == 'full'))
                connection.execute(Job.__table__.insert().values(company_id=company, owner_id=owner, kind='message', target_id=str(uuid4()), result={'executionMode': mode, 'modeRevision': 2}))
            before = list(connection.execute(select(Conversation.__table__).order_by(Conversation.id)).mappings())
            jobs = list(connection.execute(select(Job.__table__).order_by(Job.id)).mappings())
        command.upgrade(config, '0024_account_execution_mode')
        with scoped.begin() as connection:
            assert list(connection.execute(select(Conversation.__table__).order_by(Conversation.id)).mappings()) == before
            assert list(connection.execute(select(Job.__table__).order_by(Job.id)).mappings()) == jobs
            migrated_members = Table('company_member', MetaData(), autoload_with=connection)
            for old, owner in owners.items():
                member = connection.execute(select(migrated_members).where(migrated_members.c.id == owner)).mappings().one()
                assert member['execution_mode'] == ('ask' if old == 'ask' else 'auto')
                assert not member['full_access_confirmed'] and member['mode_revision'] == 1
            connection.execute(Member.__table__.update().where(Member.id == owners['full']).values(execution_mode='full', full_access_confirmed=True, mode_revision=2))
        command.downgrade(config, '0023_builtin_execution')
        with scoped.connect() as connection:
            restored = Table('company_conversation', MetaData(), autoload_with=connection)
            row = connection.execute(select(restored).where(restored.c.owner_id == owners['full'])).mappings().one()
            assert row['execution_mode'] == 'full' and row['full_access_confirmed'] and row['mode_revision'] == 2
            assert list(connection.execute(select(Job.__table__).order_by(Job.id)).mappings()) == jobs
    finally:
        scoped.dispose()
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()
