"""Use owned throwaway schemas for both fresh and existing-data upgrades."""
import os
from pathlib import Path
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema
from app.modules.members.models import Company, Member
from app.modules.announcements.models import Announcement, AnnouncementRead


@pytest.mark.parametrize('existing', [False, True])
def test_announcement_migration_preserves_existing_data_and_delete_policy(monkeypatch, existing):
    url = make_url(os.environ['DATABASE_TEST_URL']).set(drivername='postgresql+psycopg')
    assert url.database == 'paa_company_test'
    schema = 'announcement_migration_' + uuid4().hex
    engine = create_engine(url)
    scoped_url = url.update_query_dict({'options': '-csearch_path=' + schema})
    scoped = create_engine(scoped_url)
    monkeypatch.setenv('DATABASE_URL', scoped_url.render_as_string(hide_password=False))
    config = Config()
    config.set_main_option('script_location', str(Path(__file__).resolve().parents[4] / 'apps/server/app/migrations'))
    with engine.begin() as db:
        db.execute(CreateSchema(schema))
    try:
        if existing:
            command.upgrade(config, '0030_image_provider_result')
            with scoped.begin() as db:
                company = db.execute(Company.__table__.insert().values(name='旧公司').returning(Company.id)).scalar_one()
                member = db.execute(Member.__table__.insert().values(company_id=company, username='original', name='旧成员').returning(Member.id)).scalar_one()
                before = dict(db.execute(text('SELECT * FROM company_member')).mappings().one())
        command.upgrade(config, 'head')
        with scoped.begin() as db:
            assert 'company_announcement' in inspect(db).get_table_names()
            if existing:
                assert dict(db.execute(text('SELECT * FROM company_member')).mappings().one()) == before
            else:
                company = db.execute(Company.__table__.insert().values(name='新公司').returning(Company.id)).scalar_one()
                member = db.execute(Member.__table__.insert().values(company_id=company, username='new', name='发布人').returning(Member.id)).scalar_one()
            identifier = db.execute(Announcement.__table__.insert().values(company_id=company, title='公告', markdown='正文', author_id=member, editor_id=member, author_name='发布人快照', editor_name='发布人快照').returning(Announcement.id)).scalar_one()
            db.execute(AnnouncementRead.__table__.insert().values(company_id=company, announcement_id=identifier, reader_id=member, revision=1))
            db.execute(Member.__table__.delete().where(Member.id == member))
            item = db.execute(Announcement.__table__.select()).mappings().one()
            assert item['author_id'] is None and item['editor_id'] is None and item['author_name'] == '发布人快照'
            assert db.scalar(text('SELECT count(*) FROM company_announcement_read')) == 0
    finally:
        scoped.dispose()
        with engine.begin() as db:
            db.execute(DropSchema(schema, cascade=True))
        engine.dispose()
