"""Migrate only an owned throwaway schema, never the shared test schema."""
import os
from pathlib import Path
from uuid import uuid4
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text, MetaData, Table
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema
from app.modules.members.models import Company, Member
from app.modules.model_services.models import ModelRouting
from app.db.base import now
from app.modules.conversations.models import Conversation
from app.modules.messages.models import Message
from app.tasks.models import Job


def test_image_migration_roundtrip_preserves_old_accounts_and_routes(monkeypatch):
    url = make_url(os.environ['DATABASE_TEST_URL']).set(drivername='postgresql+psycopg')
    assert url.database == 'paa_company_test'
    schema = 'image_migration_' + uuid4().hex
    engine = create_engine(url)
    scoped_url = url.update_query_dict({'options': '-csearch_path=' + schema})
    scoped = create_engine(scoped_url)
    monkeypatch.setenv('DATABASE_URL', scoped_url.render_as_string(hide_password=False))
    config = Config()
    config.set_main_option('script_location', str(Path(__file__).resolve().parents[4] / 'apps/server/app/migrations'))
    with engine.begin() as db:
        db.execute(CreateSchema(schema))
    try:
        command.upgrade(config, '0028_direct_reasoning')
        with scoped.begin() as db:
            company = db.execute(Company.__table__.insert().values(name='原有公司').returning(Company.id)).scalar_one()
            member = db.execute(Member.__table__.insert().values(company_id=company, username='original', name='原有账号').returning(Member.id)).scalar_one()
            choices = {'assistant': None, 'report': 'follow', 'asr': None}
            db.execute(ModelRouting.__table__.insert().values(company_id=company, revision=7, choices=choices))
            before = dict(db.execute(text('SELECT * FROM company_member WHERE id=:id'), {'id': member}).mappings().one())
        command.upgrade(config, '0029_image_generation')
        with scoped.connect() as db:
            assert dict(db.execute(text('SELECT * FROM company_member WHERE id=:id'), {'id': member}).mappings().one()) == before
            assert db.scalar(text('SELECT choices FROM company_model_routing')) == choices
            assert db.scalar(text('SELECT revision FROM company_model_routing')) == 7
            assert db.scalar(text('SELECT count(*) FROM company_image_generation')) == 0
            unique = [set(item['column_names']) for item in inspect(db).get_unique_constraints('company_image_generation')]
            assert {'message_id', 'operation'} in unique and {'message_id', 'fingerprint'} in unique
        with scoped.begin() as db:
            conversation = db.execute(Conversation.__table__.insert().values(company_id=company, owner_id=member).returning(Conversation.id)).scalar_one()
            message = db.execute(Message.__table__.insert().values(company_id=company, owner_id=member, conversation_id=conversation).returning(Message.id)).scalar_one()
            job = db.execute(Job.__table__.insert().values(company_id=company, owner_id=member, kind='message', target_id=message).returning(Job.id)).scalar_one()
            old_images = Table('company_image_generation', MetaData(), autoload_with=db)
            db.execute(old_images.insert().values(id=str(uuid4()), created_at=now(), updated_at=now(), company_id=company, owner_id=member,
                job_id=job, conversation_id=conversation, message_id=message, operation=1, fingerprint='old-async', fence=1,
                state='polling', task_id='native-task', binding={'image': None}, request={'prompt': '旧图片'}, sources=[], files=[], result={}))
            original = dict(db.execute(text('SELECT * FROM company_image_generation')).mappings().one())
        command.upgrade(config, '0030_image_provider_result')
        with scoped.connect() as db:
            upgraded = dict(db.execute(text('SELECT * FROM company_image_generation')).mappings().one())
            assert upgraded.pop('provider_result') == {} and upgraded == original
            assert db.scalar(text('SELECT choices FROM company_model_routing')) == choices
        command.downgrade(config, '0029_image_generation')
        with scoped.connect() as db:
            assert dict(db.execute(text('SELECT * FROM company_image_generation')).mappings().one()) == original
        command.downgrade(config, '0028_direct_reasoning')
        with scoped.connect() as db:
            assert 'company_image_generation' not in inspect(db).get_table_names()
            assert db.scalar(text('SELECT count(*) FROM company_member')) == 1
            assert db.scalar(text('SELECT choices FROM company_model_routing')) == choices
    finally:
        scoped.dispose()
        with engine.begin() as db:
            db.execute(DropSchema(schema, cascade=True))
        engine.dispose()
