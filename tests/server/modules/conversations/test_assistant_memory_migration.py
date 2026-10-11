import os
from pathlib import Path
from uuid import uuid4
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema
from app.core.config import Settings


def test_memory_migration_leaves_existing_accounts_and_messages_unchanged(monkeypatch):
    Settings()
    url = make_url(os.environ['DATABASE_TEST_URL']).set(drivername='postgresql+psycopg')
    assert url.database == 'paa_company_test'
    schema = 'memory_migration_' + uuid4().hex
    engine = create_engine(url)
    scoped_url = url.update_query_dict({'options': '-csearch_path=' + schema})
    scoped = create_engine(scoped_url)
    monkeypatch.setenv('DATABASE_URL', scoped_url.render_as_string(hide_password=False))
    config = Config(); config.set_main_option('script_location', str(Path(__file__).resolve().parents[4] / 'apps/server/app/migrations'))
    with engine.begin() as db:
        db.execute(CreateSchema(schema))
    try:
        command.upgrade(config, '0025_work_records')
        with scoped.begin() as db:
            from app.modules.members.models import Company, Member
            company = db.execute(Company.__table__.insert().values(name='原有公司').returning(Company.id)).scalar_one()
            member = db.execute(Member.__table__.insert().values(company_id=company, username='original', name='原有账号').returning(Member.id)).scalar_one()
            before = dict(db.execute(text('SELECT * FROM company_member WHERE id=:id'), {'id':member}).mappings().one())
        command.upgrade(config, '0026_assistant_memory')
        with scoped.connect() as db:
            assert dict(db.execute(text('SELECT * FROM company_member WHERE id=:id'), {'id':member}).mappings().one()) == before
            assert db.scalar(text('SELECT count(*) FROM company_assistant_memory')) == 0
            assert any(set(c['column_names']) == {'company_id', 'owner_id'} for c in inspect(db).get_unique_constraints('company_assistant_memory'))
        command.downgrade(config, '0025_work_records')
        with scoped.connect() as db:
            assert 'company_assistant_memory' not in inspect(db).get_table_names()
            assert db.scalar(text('SELECT count(*) FROM company_member')) == 1
    finally:
        scoped.dispose()
        with engine.begin() as db:
            db.execute(DropSchema(schema, cascade=True))
        engine.dispose()
