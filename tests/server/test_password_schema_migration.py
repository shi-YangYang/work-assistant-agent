"""Exercise the real migration chain in a disposable PostgreSQL schema."""
import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema

from paa_server.config import Settings
from paa_server.models import Company, Member, WorkItem, now


def test_password_flag_migration_preserves_accounts_and_work(monkeypatch):
    Settings()  # Load the same local configuration as the API test suite.
    url = make_url(os.environ['DATABASE_TEST_URL']).set(drivername='postgresql+psycopg')
    assert url.database == 'paa_company_test', 'Refusing migration tests outside the test database'
    schema = 'password_migration_' + uuid4().hex
    engine = create_engine(url)
    scoped_url = url.update_query_dict({'options': '-csearch_path=' + schema})
    scoped = create_engine(scoped_url)
    monkeypatch.setenv('DATABASE_URL', scoped_url.render_as_string(hide_password=False))
    config = Config()
    config.set_main_option('script_location', str(Path(__file__).resolve().parents[2] / 'services/company/src/paa_server/migrations'))
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
        # Building from an empty schema also checks that historical migrations remain valid.
        command.upgrade(config, '0012_member_deletion')
        with scoped.begin() as connection:
            company_id = connection.execute(Company.__table__.insert().values(name='迁移验证公司').returning(Company.id)).scalar_one()
            previous = Table('company_member', MetaData(), autoload_with=connection)
            for flag in (True, False):
                connection.execute(previous.insert().values(
                    id=str(uuid4()), company_id=company_id, username='migration_' + str(flag),
                    name='原有员工', role='employee', password_hash='unchanged-existing-hash',
                    active=True, deleted=False, must_change_password=flag, created_at=now(),
                ))
            before = [dict(row) for row in connection.execute(select(previous).order_by(previous.c.id)).mappings()]
            connection.execute(WorkItem.__table__.insert().values(
                company_id=company_id, owner_id=before[0]['id'], title='原有工作', content={'title': '原有工作'},
            ))
            work_before = list(connection.execute(select(WorkItem.__table__)).mappings())

        command.upgrade(config, 'head')
        with scoped.begin() as connection:
            assert 'must_change_password' not in {column['name'] for column in inspect(connection).get_columns('company_member')}
            assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0013_drop_password_change'
            after = list(connection.execute(select(Member.__table__).order_by(Member.id)).mappings())
            assert after == [{key: value for key, value in row.items() if key != 'must_change_password'} for row in before]
            assert list(connection.execute(select(WorkItem.__table__)).mappings()) == work_before
            # New accounts no longer need a value for the old NOT NULL column.
            connection.execute(Member.__table__.insert().values(
                company_id=company_id, username='migration_new', name='新成员', password_hash='new-hash',
            ))

        command.downgrade(config, '0012_member_deletion')
        with scoped.connect() as connection:
            assert connection.scalar(text('SELECT count(*) FROM company_member WHERE must_change_password IS FALSE')) == 3
            assert list(connection.execute(select(WorkItem.__table__)).mappings()) == work_before
        command.upgrade(config, 'head')
        with scoped.connect() as connection:
            assert 'must_change_password' not in {column['name'] for column in inspect(connection).get_columns('company_member')}
            assert connection.scalar(text('SELECT count(*) FROM company_member')) == 3
    finally:
        scoped.dispose()
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()
